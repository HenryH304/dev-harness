"""Tests for US-022: Admin dashboard — agent monitor and metrics."""

import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import AgentRegistry, Ticket


@pytest.fixture
async def db_session():
    """Create an in-memory database session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def app_client(db_session: AsyncSession):
    """Create a test client with mocked dependencies."""
    from unittest import mock

    from app.main import app
    from app.routers.dashboard import _get_session

    async def override_session():  # type: ignore[misc]
        yield db_session

    app.dependency_overrides[_get_session] = override_session

    with mock.patch("app.routers.dashboard.publish_event", new_callable=mock.AsyncMock):
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    app.dependency_overrides.clear()


# --- GET /api/dashboard/agents ---


@pytest.mark.asyncio
async def test_get_active_agents_empty(app_client: AsyncClient) -> None:
    """Returns empty list when no busy agents."""
    resp = await app_client.get("/api/dashboard/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agents"] == []


@pytest.mark.asyncio
async def test_get_active_agents_shows_busy(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Returns busy agents with ticket info and elapsed time."""
    # Create a ticket
    ticket = Ticket(
        project="proj",
        title="Test ticket",
        description="desc",
        acceptance_criteria=[],
        priority=1,
        state="in_progress",
        current_agent="developer-abc123",
        assigned_at=datetime.datetime(2026, 3, 16, 10, 0, 0),
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    # Create agent registry entry
    agent = AgentRegistry(
        agent_type="developer",
        status="busy",
        current_ticket_id=ticket.id,
        started_at=datetime.datetime(2026, 3, 16, 10, 0, 0),
    )
    db_session.add(agent)
    await db_session.commit()

    resp = await app_client.get("/api/dashboard/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["agents"]) == 1
    agent_data = data["agents"][0]
    assert agent_data["agent_type"] == "developer"
    assert agent_data["status"] == "busy"
    assert agent_data["current_ticket_id"] == ticket.id
    assert agent_data["ticket_title"] == "Test ticket"
    assert "elapsed_seconds" in agent_data


@pytest.mark.asyncio
async def test_get_active_agents_excludes_available(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Available agents are excluded from the active agents list."""
    agent = AgentRegistry(
        agent_type="reviewer",
        status="available",
        current_ticket_id=None,
        started_at=None,
    )
    db_session.add(agent)
    await db_session.commit()

    resp = await app_client.get("/api/dashboard/agents")
    assert resp.status_code == 200
    assert len(resp.json()["agents"]) == 0


# --- GET /api/dashboard/metrics ---


@pytest.mark.asyncio
async def test_get_metrics_empty(app_client: AsyncClient) -> None:
    """Returns zero counts when no tickets exist."""
    resp = await app_client.get("/api/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "column_counts" in data
    assert data["column_counts"]["to_do"] == 0
    assert data["column_counts"]["done"] == 0
    assert "total_tickets" in data
    assert data["total_tickets"] == 0


@pytest.mark.asyncio
async def test_get_metrics_with_tickets(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Returns correct counts per column."""
    for i in range(3):
        db_session.add(
            Ticket(
                project="proj",
                title=f"Todo {i}",
                description="d",
                acceptance_criteria=[],
                priority=1,
                state="to_do",
            )
        )
    db_session.add(
        Ticket(
            project="proj",
            title="In progress",
            description="d",
            acceptance_criteria=[],
            priority=1,
            state="in_progress",
        )
    )
    db_session.add(
        Ticket(
            project="proj",
            title="Done",
            description="d",
            acceptance_criteria=[],
            priority=1,
            state="done",
        )
    )
    await db_session.commit()

    resp = await app_client.get("/api/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["column_counts"]["to_do"] == 3
    assert data["column_counts"]["in_progress"] == 1
    assert data["column_counts"]["done"] == 1
    assert data["total_tickets"] == 5


# --- GET /api/dashboard/timeouts ---


@pytest.mark.asyncio
async def test_get_timeout_analytics_empty(app_client: AsyncClient) -> None:
    """Returns zero timeout counts when no tickets exist."""
    resp = await app_client.get("/api/dashboard/timeouts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["developer_timeouts"] == 0
    assert data["reviewer_timeouts"] == 0
    assert data["tester_timeouts"] == 0
    assert data["merger_timeouts"] == 0


@pytest.mark.asyncio
async def test_get_timeout_analytics_aggregated(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Returns aggregated timeout counts across all tickets."""
    db_session.add(
        Ticket(
            project="proj",
            title="T1",
            description="d",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
            developer_timeouts=2,
            reviewer_timeouts=1,
        )
    )
    db_session.add(
        Ticket(
            project="proj",
            title="T2",
            description="d",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
            developer_timeouts=1,
            tester_timeouts=3,
        )
    )
    await db_session.commit()

    resp = await app_client.get("/api/dashboard/timeouts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["developer_timeouts"] == 3
    assert data["reviewer_timeouts"] == 1
    assert data["tester_timeouts"] == 3
    assert data["merger_timeouts"] == 0


# --- GET /api/dashboard/blocked ---


@pytest.mark.asyncio
async def test_get_blocked_tickets_empty(app_client: AsyncClient) -> None:
    """Returns empty list when no blocked tickets."""
    resp = await app_client.get("/api/dashboard/blocked")
    assert resp.status_code == 200
    assert resp.json()["blocked_tickets"] == []


@pytest.mark.asyncio
async def test_get_blocked_tickets_shows_blocked(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Returns blocked tickets with rejection counts."""
    db_session.add(
        Ticket(
            project="proj",
            title="Blocked ticket",
            description="d",
            acceptance_criteria=[],
            priority=1,
            state="blocked",
            review_rejection_count=3,
        )
    )
    db_session.add(
        Ticket(
            project="proj",
            title="Normal ticket",
            description="d",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
        )
    )
    await db_session.commit()

    resp = await app_client.get("/api/dashboard/blocked")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["blocked_tickets"]) == 1
    assert data["blocked_tickets"][0]["title"] == "Blocked ticket"
    assert data["blocked_tickets"][0]["review_rejection_count"] == 3


# --- POST /api/dashboard/force-unlock/{ticket_id} ---


@pytest.mark.asyncio
async def test_force_unlock_stuck_ticket(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Force unlock releases agent from a stuck ticket."""
    ticket = Ticket(
        project="proj",
        title="Stuck ticket",
        description="d",
        acceptance_criteria=[],
        priority=1,
        state="in_progress",
        current_agent="developer-xyz",
        assigned_at=datetime.datetime(2026, 3, 16, 10, 0, 0),
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    agent = AgentRegistry(
        agent_type="developer",
        status="busy",
        current_ticket_id=ticket.id,
        started_at=datetime.datetime(2026, 3, 16, 10, 0, 0),
    )
    db_session.add(agent)
    await db_session.commit()

    resp = await app_client.post(f"/api/dashboard/force-unlock/{ticket.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "to_do"
    assert data["current_agent"] is None


@pytest.mark.asyncio
async def test_force_unlock_not_found(app_client: AsyncClient) -> None:
    """Returns 404 for non-existent ticket."""
    resp = await app_client.post("/api/dashboard/force-unlock/999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_force_unlock_no_agent(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Returns 400 when ticket has no assigned agent."""
    ticket = Ticket(
        project="proj",
        title="Free ticket",
        description="d",
        acceptance_criteria=[],
        priority=1,
        state="to_do",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    resp = await app_client.post(f"/api/dashboard/force-unlock/{ticket.id}")
    assert resp.status_code == 400


# --- POST /api/dashboard/toggle-agents ---


@pytest.mark.asyncio
async def test_toggle_agents_pause(app_client: AsyncClient) -> None:
    """Toggle agents to paused state."""
    resp = await app_client.post(
        "/api/dashboard/toggle-agents", json={"paused": True}
    )
    assert resp.status_code == 200
    assert resp.json()["agents_paused"] is True


@pytest.mark.asyncio
async def test_toggle_agents_resume(app_client: AsyncClient) -> None:
    """Toggle agents to resumed state."""
    # First pause
    await app_client.post("/api/dashboard/toggle-agents", json={"paused": True})
    # Then resume
    resp = await app_client.post(
        "/api/dashboard/toggle-agents", json={"paused": False}
    )
    assert resp.status_code == 200
    assert resp.json()["agents_paused"] is False
