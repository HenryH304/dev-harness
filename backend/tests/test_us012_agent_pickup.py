"""Tests for US-012: Agent pickup and locking system."""

import datetime
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AgentRegistry, Setting, Ticket


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
    from app.routers.transitions import _get_session as _get_session_transitions

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[_get_session] = override_session
    app.dependency_overrides[_get_session_transitions] = override_session

    # Mock init_db, close_redis, and publish_event to avoid real connections
    with (
        mock.patch("app.main.init_db"),
        mock.patch("app.main.close_redis"),
        mock.patch("app.main.redis_listener"),
        mock.patch("app.routers.agents.publish_event"),
    ):
        yield app

    app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def seed_tickets(session_factory):
    """Create test tickets in various states."""
    async with session_factory() as session:
        tickets = [
            Ticket(
                project="proj-a",
                title="Task 1",
                description="Desc 1",
                acceptance_criteria=[],
                priority=1,
                state="to_do",
            ),
            Ticket(
                project="proj-a",
                title="Task 2",
                description="Desc 2",
                acceptance_criteria=[],
                priority=2,
                state="to_do",
            ),
            Ticket(
                project="proj-b",
                title="Task 3",
                description="Desc 3",
                acceptance_criteria=[],
                priority=1,
                state="ready_for_review",
            ),
            Ticket(
                project="proj-a",
                title="Task 4",
                description="Desc 4",
                acceptance_criteria=[],
                priority=1,
                state="ready_for_test",
            ),
            Ticket(
                project="proj-a",
                title="Task 5",
                description="Desc 5",
                acceptance_criteria=[],
                priority=1,
                state="ready_to_merge",
            ),
        ]
        session.add_all(tickets)
        await session.commit()
        return tickets


# --- Basic pickup tests ---


@pytest.mark.asyncio
async def test_pickup_developer_finds_todo_ticket(client, seed_tickets):
    """Developer agent picks up a to_do ticket and moves it to in_progress."""
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "in_progress"
    assert data["current_agent"] is not None
    assert "developer" in data["current_agent"]


@pytest.mark.asyncio
async def test_pickup_reviewer_finds_ready_for_review_ticket(client, seed_tickets):
    """Reviewer agent picks up a ready_for_review ticket and moves it to in_review."""
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/reviewer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "in_review"


@pytest.mark.asyncio
async def test_pickup_tester_finds_ready_for_test_ticket(client, seed_tickets):
    """Tester agent picks up a ready_for_test ticket and moves it to in_test."""
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/tester")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "in_test"


@pytest.mark.asyncio
async def test_pickup_merger_finds_ready_to_merge_ticket(client, seed_tickets):
    """Merger agent picks up a ready_to_merge ticket."""
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/merger")
    assert resp.status_code == 200
    data = resp.json()
    # Merger stays in ready_to_merge (no "in_merge" state) — completion moves to done
    assert data["state"] == "ready_to_merge"


@pytest.mark.asyncio
async def test_pickup_increments_agent_attempts(client, seed_tickets):
    """Pickup should increment agent_attempts on the ticket."""
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_attempts"] == 1


@pytest.mark.asyncio
async def test_pickup_registers_agent(client, seed_tickets, session_factory):
    """Pickup should register the agent in agent_registry."""
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200

    # Check agent registry
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(AgentRegistry).where(AgentRegistry.status == "busy")
        )
        agent = result.scalar_one_or_none()
        assert agent is not None
        assert agent.agent_type == "developer"
        assert agent.current_ticket_id == resp.json()["id"]


# --- No available tickets ---


@pytest.mark.asyncio
async def test_pickup_no_available_tickets(client, seed_tickets):
    """Returns 404 when no tickets match the agent type's column binding."""
    # There are no "to_do" tickets after they're all picked up or there are none
    # Use an agent type that has no matching tickets — tester has 1, but let's pick it
    # Then try again
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp1 = await client.post("/api/agents/pickup/tester")
    assert resp1.status_code == 200

    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp2 = await client.post("/api/agents/pickup/tester")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_pickup_invalid_agent_type(client):
    """Returns 400 for unknown agent type."""
    resp = await client.post("/api/agents/pickup/unknown")
    assert resp.status_code == 400
    assert "Unknown agent type" in resp.json()["detail"]


# --- Redis distributed lock ---


@pytest.mark.asyncio
async def test_pickup_lock_failure_tries_next(client, seed_tickets):
    """If Redis lock fails for first ticket, tries next available ticket."""
    call_count = 0

    async def mock_acquire(ticket_id, agent_id, ttl=30):
        nonlocal call_count
        call_count += 1
        # Fail on first attempt, succeed on second
        return call_count > 1

    with mock.patch("app.routers.agents.acquire_lock", side_effect=mock_acquire):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200
    # Should have tried 2 tickets
    assert call_count == 2


@pytest.mark.asyncio
async def test_pickup_all_locks_fail(client, seed_tickets):
    """Returns 409 when all candidate tickets are locked."""
    with mock.patch("app.routers.agents.acquire_lock", return_value=False):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 409
    assert "locked" in resp.json()["detail"].lower()


# --- System-wide agent cap ---


@pytest.mark.asyncio
async def test_pickup_at_capacity_returns_429(client, seed_tickets, session_factory):
    """Returns 429 when system-wide agent cap is reached."""
    # Fill agent registry to capacity (default max_agents_system=10)
    async with session_factory() as session:
        for i in range(10):
            agent = AgentRegistry(
                agent_type="developer",
                status="busy",
                current_ticket_id=None,
                started_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(agent)
        await session.commit()

    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 429
    assert "capacity" in resp.json()["detail"].lower()


# --- Priority project ---


@pytest.mark.asyncio
async def test_pickup_prioritises_active_project(client, session_factory):
    """Tickets from the active priority project are picked first."""
    async with session_factory() as session:
        # Create tickets in two projects
        t1 = Ticket(
            project="proj-b",
            title="Low priority project task",
            description="D",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
        )
        t2 = Ticket(
            project="proj-a",
            title="Priority project task",
            description="D",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
        )
        # Set active priority project
        setting = Setting(key="active_priority_project", value="proj-a")
        session.add_all([t1, t2, setting])
        await session.commit()

    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "proj-a"


# --- WIP reduction priority ---


@pytest.mark.asyncio
async def test_wip_priority_merger_over_developer(client, session_factory):
    """When near cap, merger agents should be allowed over developer agents."""
    async with session_factory() as session:
        # Create tickets for both types
        t1 = Ticket(
            project="proj-a",
            title="Dev task",
            description="D",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
        )
        t2 = Ticket(
            project="proj-a",
            title="Merge task",
            description="D",
            acceptance_criteria=[],
            priority=1,
            state="ready_to_merge",
        )
        session.add_all([t1, t2])

        # Fill to near capacity (9 out of 10)
        for i in range(9):
            agent = AgentRegistry(
                agent_type="developer",
                status="busy",
                current_ticket_id=None,
                started_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(agent)
        await session.commit()

    # Merger should still be allowed (higher WIP priority)
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp_merger = await client.post("/api/agents/pickup/merger")
    assert resp_merger.status_code == 200

    # Developer should be rejected when at cap
    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp_dev = await client.post("/api/agents/pickup/developer")
    assert resp_dev.status_code == 429


# --- Publishes agent_assigned event ---


@pytest.mark.asyncio
async def test_pickup_publishes_agent_assigned_event(client, seed_tickets):
    """Pickup should publish an agent_assigned event to Redis."""
    # Need a fresh mock to capture call args (fixture already mocks publish_event)
    mock_publish = mock.AsyncMock()
    with (
        mock.patch("app.routers.agents.acquire_lock", return_value=True),
        mock.patch("app.routers.agents.publish_event", mock_publish),
    ):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200
    mock_publish.assert_called_once()
    call_args = mock_publish.call_args
    assert call_args[0][0] == "ticket:events"
    event = call_args[0][1]
    assert event["event_type"] == "agent_assigned"


# --- Skips already-assigned tickets ---


@pytest.mark.asyncio
async def test_pickup_skips_already_assigned_tickets(client, session_factory):
    """Tickets with a current_agent should not be picked up."""
    async with session_factory() as session:
        t1 = Ticket(
            project="proj-a",
            title="Already assigned",
            description="D",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
            current_agent="developer-abc",
        )
        t2 = Ticket(
            project="proj-a",
            title="Available",
            description="D",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
        )
        session.add_all([t1, t2])
        await session.commit()

    with mock.patch("app.routers.agents.acquire_lock", return_value=True):
        resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Available"
