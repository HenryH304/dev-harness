"""Tests for US-013: Agent completion and failure flow."""

import datetime
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AgentRegistry, Note, Ticket


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine):
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def app(engine, session_factory):
    from app.main import app
    from app.routers.agents import _get_session
    from app.routers.notes import _get_session as _get_session_notes
    from app.routers.tickets import _get_session as _get_session_tickets
    from app.routers.transitions import _get_session as _get_session_transitions

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[_get_session] = override_session
    app.dependency_overrides[_get_session_transitions] = override_session
    app.dependency_overrides[_get_session_tickets] = override_session
    app.dependency_overrides[_get_session_notes] = override_session

    with (
        mock.patch("app.main.init_db"),
        mock.patch("app.main.close_redis"),
        mock.patch("app.main.redis_listener"),
        mock.patch("app.routers.agents.publish_event"),
        mock.patch("app.routers.transitions.publish_event"),
    ):
        yield app

    app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def assigned_ticket(session_factory) -> tuple[int, str, int]:
    """Create a ticket in in_progress with an assigned agent.

    Returns (ticket_id, agent_id, agent_registry_id).
    """
    async with session_factory() as session:
        ticket = Ticket(
            project="proj-a",
            title="Task in progress",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="in_progress",
            current_agent="developer-abc12345",
            assigned_at=datetime.datetime.now(datetime.timezone.utc),
            agent_attempts=1,
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id

        agent = AgentRegistry(
            agent_type="developer",
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(agent)
        await session.commit()
        return ticket_id, "developer-abc12345", agent.id


@pytest.fixture
async def review_ticket(session_factory) -> tuple[int, str, int]:
    """Create a ticket in in_review with assigned reviewer."""
    async with session_factory() as session:
        ticket = Ticket(
            project="proj-a",
            title="Task in review",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="in_review",
            current_agent="reviewer-xyz99999",
            assigned_at=datetime.datetime.now(datetime.timezone.utc),
            agent_attempts=1,
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id

        agent = AgentRegistry(
            agent_type="reviewer",
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(agent)
        await session.commit()
        return ticket_id, "reviewer-xyz99999", agent.id


# --- Complete endpoint tests ---


@pytest.mark.asyncio
async def test_complete_advances_ticket_to_next_state(client, assigned_ticket):
    """POST /api/agents/complete/{ticket_id} advances to next state."""
    ticket_id, agent_id, _ = assigned_ticket
    resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 200
    data = resp.json()
    # in_progress -> ready_for_review
    assert data["state"] == "ready_for_review"
    assert data["current_agent"] is None


@pytest.mark.asyncio
async def test_complete_releases_agent_lock(
    client, assigned_ticket, session_factory
):
    """Completion releases the agent lock and updates agent registry."""
    ticket_id, agent_id, agent_reg_id = assigned_ticket
    resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 200

    async with session_factory() as session:
        result = await session.execute(
            select(AgentRegistry).where(AgentRegistry.id == agent_reg_id)
        )
        agent = result.scalar_one()
        assert agent.status == "available"
        assert agent.current_ticket_id is None


@pytest.mark.asyncio
async def test_complete_publishes_agent_completed_event(client, assigned_ticket):
    """Completion publishes agent_completed event to Redis."""
    ticket_id, _, _ = assigned_ticket
    mock_publish = mock.AsyncMock()
    with mock.patch("app.routers.agents.publish_event", mock_publish):
        resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 200
    mock_publish.assert_called_once()
    event = mock_publish.call_args[0][1]
    assert event["event_type"] == "agent_completed"
    assert event["ticket_id"] == ticket_id


@pytest.mark.asyncio
async def test_complete_reviewer_advances_to_ready_for_test(
    client, review_ticket
):
    """Reviewer completion advances from in_review to ready_for_test."""
    ticket_id, _, _ = review_ticket
    resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "ready_for_test"


@pytest.mark.asyncio
async def test_complete_merger_advances_to_done(client, session_factory):
    """Merger completion advances from ready_to_merge to done."""
    async with session_factory() as session:
        ticket = Ticket(
            project="proj-a",
            title="Ready to merge",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="ready_to_merge",
            current_agent="merger-aaa11111",
            assigned_at=datetime.datetime.now(datetime.timezone.utc),
            agent_attempts=1,
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id
        agent = AgentRegistry(
            agent_type="merger",
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(agent)
        await session.commit()

    resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "done"


@pytest.mark.asyncio
async def test_complete_nonexistent_ticket(client):
    """Returns 404 for nonexistent ticket."""
    resp = await client.post("/api/agents/complete/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_complete_unassigned_ticket(client, session_factory):
    """Returns 400 for ticket with no assigned agent."""
    async with session_factory() as session:
        ticket = Ticket(
            project="proj-a",
            title="Unassigned",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="in_progress",
        )
        session.add(ticket)
        await session.commit()
        ticket_id = ticket.id

    resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 400


# --- Fail endpoint tests ---


@pytest.mark.asyncio
async def test_fail_returns_ticket_to_todo(client, assigned_ticket):
    """POST /api/agents/fail/{ticket_id} returns ticket to to_do."""
    ticket_id, _, _ = assigned_ticket
    resp = await client.post(
        f"/api/agents/fail/{ticket_id}",
        json={"reason": "Tests failed", "suggested_fixes": "Fix the tests"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "to_do"
    assert data["current_agent"] is None


@pytest.mark.asyncio
async def test_fail_adds_failure_note(
    client, assigned_ticket, session_factory
):
    """Failure adds a failure note to the ticket."""
    ticket_id, _, _ = assigned_ticket
    resp = await client.post(
        f"/api/agents/fail/{ticket_id}",
        json={"reason": "Compilation error", "suggested_fixes": "Check imports"},
    )
    assert resp.status_code == 200

    async with session_factory() as session:
        result = await session.execute(
            select(Note).where(Note.ticket_id == ticket_id)
        )
        notes = list(result.scalars().all())
        assert len(notes) >= 1
        failure_note = notes[0]
        assert failure_note.note_type == "failure"
        assert "Compilation error" in failure_note.content


@pytest.mark.asyncio
async def test_fail_releases_agent_lock(
    client, assigned_ticket, session_factory
):
    """Failure releases the agent lock."""
    ticket_id, _, agent_reg_id = assigned_ticket
    await client.post(
        f"/api/agents/fail/{ticket_id}",
        json={"reason": "Failed"},
    )

    async with session_factory() as session:
        result = await session.execute(
            select(AgentRegistry).where(AgentRegistry.id == agent_reg_id)
        )
        agent = result.scalar_one()
        assert agent.status == "available"
        assert agent.current_ticket_id is None


@pytest.mark.asyncio
async def test_fail_reviewer_increments_rejection_count(
    client, review_ticket
):
    """Reviewer failure increments review_rejection_count."""
    ticket_id, _, _ = review_ticket
    resp = await client.post(
        f"/api/agents/fail/{ticket_id}",
        json={"reason": "Code quality issues"},
    )
    assert resp.status_code == 200
    assert resp.json()["review_rejection_count"] == 1


@pytest.mark.asyncio
async def test_fail_developer_does_not_increment_rejection_count(
    client, assigned_ticket
):
    """Developer failure does not increment review_rejection_count."""
    ticket_id, _, _ = assigned_ticket
    resp = await client.post(
        f"/api/agents/fail/{ticket_id}",
        json={"reason": "Build failed"},
    )
    assert resp.status_code == 200
    assert resp.json()["review_rejection_count"] == 0


@pytest.mark.asyncio
async def test_fail_publishes_agent_failed_event(client, assigned_ticket):
    """Failure publishes agent_failed event to Redis."""
    ticket_id, _, _ = assigned_ticket
    mock_publish = mock.AsyncMock()
    with mock.patch("app.routers.agents.publish_event", mock_publish):
        resp = await client.post(
            f"/api/agents/fail/{ticket_id}",
            json={"reason": "Error occurred"},
        )
    assert resp.status_code == 200
    mock_publish.assert_called_once()
    event = mock_publish.call_args[0][1]
    assert event["event_type"] == "agent_failed"


@pytest.mark.asyncio
async def test_fail_nonexistent_ticket(client):
    """Returns 404 for nonexistent ticket."""
    resp = await client.post(
        "/api/agents/fail/9999",
        json={"reason": "Error"},
    )
    assert resp.status_code == 404


# --- Review rejection threshold / blocked ---


@pytest.mark.asyncio
async def test_fail_reviewer_blocks_at_threshold(client, session_factory):
    """After reaching rejection threshold, ticket is blocked."""
    async with session_factory() as session:
        ticket = Ticket(
            project="proj-a",
            title="Repeatedly rejected",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="in_review",
            current_agent="reviewer-block01",
            assigned_at=datetime.datetime.now(datetime.timezone.utc),
            agent_attempts=3,
            review_rejection_count=2,  # threshold is 3, this will be #3
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id
        agent = AgentRegistry(
            agent_type="reviewer",
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(agent)
        await session.commit()

    mock_publish = mock.AsyncMock()
    with mock.patch("app.routers.agents.publish_event", mock_publish):
        resp = await client.post(
            f"/api/agents/fail/{ticket_id}",
            json={"reason": "Still bad code"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "blocked"
    assert data["review_rejection_count"] == 3

    # Should have published ticket_blocked event
    calls = mock_publish.call_args_list
    event_types = [c[0][1]["event_type"] for c in calls]
    assert "ticket_blocked" in event_types


# --- Timeout detection ---


@pytest.mark.asyncio
async def test_timeout_detection_releases_timed_out_agents(
    client, session_factory
):
    """Background timeout check releases agents that exceeded their timeout."""
    from app.routers.agents import check_agent_timeouts

    async with session_factory() as session:
        # Create a ticket assigned to a developer 25 minutes ago (timeout is 20min)
        ticket = Ticket(
            project="proj-a",
            title="Timed out task",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="in_progress",
            current_agent="developer-timeout1",
            assigned_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=25),
            agent_attempts=1,
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id

        agent = AgentRegistry(
            agent_type="developer",
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=25),
        )
        session.add(agent)
        await session.commit()
        agent_id = agent.id

    # Run timeout check
    mock_publish = mock.AsyncMock()
    with mock.patch("app.routers.agents.publish_event", mock_publish):
        await check_agent_timeouts(session_factory)

    # Verify ticket was released
    async with session_factory() as session:
        result = await session.execute(
            select(Ticket).where(Ticket.id == ticket_id)
        )
        ticket = result.scalar_one()
        assert ticket.state == "to_do"
        assert ticket.current_agent is None
        assert ticket.developer_timeouts == 1

        # Agent registry should be updated
        result = await session.execute(
            select(AgentRegistry).where(AgentRegistry.id == agent_id)
        )
        agent = result.scalar_one()
        assert agent.status == "available"
        assert agent.current_ticket_id is None


@pytest.mark.asyncio
async def test_timeout_does_not_release_within_limit(session_factory):
    """Agents within their timeout limit should not be released."""
    from app.routers.agents import check_agent_timeouts

    async with session_factory() as session:
        # Create a ticket assigned to a developer 5 minutes ago (timeout is 20min)
        ticket = Ticket(
            project="proj-a",
            title="Still working",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="in_progress",
            current_agent="developer-ok1",
            assigned_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=5),
            agent_attempts=1,
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id

        agent = AgentRegistry(
            agent_type="developer",
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=5),
        )
        session.add(agent)
        await session.commit()

    mock_publish = mock.AsyncMock()
    with mock.patch("app.routers.agents.publish_event", mock_publish):
        await check_agent_timeouts(session_factory)

    # Verify ticket was NOT released
    async with session_factory() as session:
        result = await session.execute(
            select(Ticket).where(Ticket.id == ticket_id)
        )
        ticket = result.scalar_one()
        assert ticket.state == "in_progress"
        assert ticket.current_agent == "developer-ok1"
        assert ticket.developer_timeouts == 0


@pytest.mark.asyncio
async def test_timeout_increments_correct_timeout_counter(session_factory):
    """Timeout increments the correct timeout counter per agent type."""
    from app.routers.agents import check_agent_timeouts

    async with session_factory() as session:
        # Reviewer that timed out (timeout is 10 min)
        ticket = Ticket(
            project="proj-a",
            title="Reviewer timed out",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="in_review",
            current_agent="reviewer-timeout1",
            assigned_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=15),
            agent_attempts=1,
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id

        agent = AgentRegistry(
            agent_type="reviewer",
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=15),
        )
        session.add(agent)
        await session.commit()

    mock_publish = mock.AsyncMock()
    with mock.patch("app.routers.agents.publish_event", mock_publish):
        await check_agent_timeouts(session_factory)

    async with session_factory() as session:
        result = await session.execute(
            select(Ticket).where(Ticket.id == ticket_id)
        )
        ticket = result.scalar_one()
        assert ticket.reviewer_timeouts == 1
        assert ticket.developer_timeouts == 0  # Not incremented
        assert ticket.state == "to_do"
