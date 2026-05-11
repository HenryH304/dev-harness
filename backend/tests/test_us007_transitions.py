"""Tests for US-007: State transition API with validation."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.main import app
from app.routers.dependencies import _get_session as deps_get_session
from app.routers.notes import _get_session as notes_get_session
from app.routers.tickets import _get_session as tickets_get_session
from app.routers.transitions import _get_session as transitions_get_session


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
async def session() -> AsyncSession:  # type: ignore[misc]
    """Create an in-memory SQLite database for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncSession:  # type: ignore[misc]
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[tickets_get_session] = override_session
    app.dependency_overrides[transitions_get_session] = override_session
    app.dependency_overrides[deps_get_session] = override_session
    app.dependency_overrides[notes_get_session] = override_session

    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture()
async def client(session: AsyncSession) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture()
async def ticket_id(client: AsyncClient) -> int:
    """Create a ticket in to_do state and return its ID."""
    resp = await client.post(
        "/api/tickets",
        json={
            "project": "test-project",
            "title": "Transition Test Ticket",
            "description": "Testing state transitions",
            "acceptance_criteria": ["AC1"],
            "priority": 1,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# --- Valid transition tests ---


VALID_TRANSITIONS = [
    ("to_do", "in_progress"),
    ("in_progress", "ready_for_review"),
    ("ready_for_review", "in_review"),
    ("in_review", "ready_for_test"),
    ("ready_for_test", "in_test"),
    ("in_test", "ready_for_merge"),
    ("ready_for_merge", "in_merge"),
    ("in_merge", "done"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("from_state,to_state", VALID_TRANSITIONS)
async def test_valid_forward_transitions(
    client: AsyncClient, ticket_id: int, from_state: str, to_state: str
) -> None:
    """Valid forward transitions should succeed."""
    # Set ticket to from_state first (skip if already to_do)
    if from_state != "to_do":
        await client.patch(
            f"/api/tickets/{ticket_id}", json={"state": from_state}
        )

    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": to_state, "agent_id": "agent-1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == to_state


@pytest.mark.anyio
async def test_transition_to_blocked_from_any_state(
    client: AsyncClient, ticket_id: int
) -> None:
    """Any state can transition to blocked."""
    states_to_test = [
        "to_do",
        "in_progress",
        "ready_for_review",
        "in_review",
        "ready_for_test",
        "in_test",
        "ready_for_merge",
        "in_merge",
    ]
    for i, state in enumerate(states_to_test):
        # Create a fresh ticket for each test
        resp = await client.post(
            "/api/tickets",
            json={
                "project": "test-project",
                "title": f"Blocked test {i}",
                "description": "test",
                "acceptance_criteria": [],
                "priority": 1,
            },
        )
        tid = resp.json()["id"]
        if state != "to_do":
            await client.patch(f"/api/tickets/{tid}", json={"state": state})

        with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
            resp = await client.post(
                f"/api/tickets/{tid}/transition",
                json={"new_state": "blocked", "agent_id": "agent-1"},
            )
        assert resp.status_code == 200, f"Failed to transition from {state} to blocked"
        assert resp.json()["state"] == "blocked"


# --- Invalid transition tests ---


INVALID_TRANSITIONS = [
    ("to_do", "ready_for_review"),
    ("to_do", "in_review"),
    ("to_do", "done"),
    ("in_progress", "to_do"),
    ("in_progress", "in_test"),
    ("ready_for_review", "in_progress"),
    ("done", "to_do"),
    ("done", "in_progress"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("from_state,to_state", INVALID_TRANSITIONS)
async def test_invalid_transitions_rejected(
    client: AsyncClient, ticket_id: int, from_state: str, to_state: str
) -> None:
    """Invalid transitions should return 400."""
    if from_state != "to_do":
        await client.patch(
            f"/api/tickets/{ticket_id}", json={"state": from_state}
        )

    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": to_state, "agent_id": "agent-1"},
        )
    assert resp.status_code == 400
    assert "transition" in resp.json()["detail"].lower()


# --- Blocked ticket transition tests ---


@pytest.mark.anyio
async def test_blocked_ticket_cannot_transition_without_override(
    client: AsyncClient, ticket_id: int
) -> None:
    """Blocked tickets cannot transition without manual_override flag."""
    # Move to blocked
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "blocked", "agent_id": "agent-1"},
        )

    # Try to move out of blocked without override
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "to_do", "agent_id": "agent-1"},
        )
    assert resp.status_code == 400
    assert "override" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_blocked_ticket_transitions_with_override(
    client: AsyncClient, ticket_id: int
) -> None:
    """Blocked tickets can transition with manual_override flag."""
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "blocked", "agent_id": "agent-1"},
        )

    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={
                "new_state": "to_do",
                "agent_id": "agent-1",
                "manual_override": True,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["state"] == "to_do"


# --- Dependency enforcement tests ---


@pytest.mark.anyio
async def test_transition_blocked_by_unresolved_dependencies(
    client: AsyncClient, ticket_id: int
) -> None:
    """Cannot transition to in_progress if dependencies are not done."""
    # Create a dependency ticket
    resp = await client.post(
        "/api/tickets",
        json={
            "project": "test-project",
            "title": "Dependency Ticket",
            "description": "Must be done first",
            "acceptance_criteria": [],
            "priority": 1,
        },
    )
    dep_id = resp.json()["id"]

    # Add dependency
    await client.post(
        f"/api/tickets/{ticket_id}/dependencies",
        json={"depends_on_ticket_id": dep_id},
    )

    # Try to transition — should fail
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "in_progress", "agent_id": "agent-1"},
        )
    assert resp.status_code == 400
    assert "dependenc" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_transition_allowed_when_dependencies_done(
    client: AsyncClient, ticket_id: int
) -> None:
    """Can transition to in_progress when all dependencies are done."""
    # Create and complete dependency ticket
    resp = await client.post(
        "/api/tickets",
        json={
            "project": "test-project",
            "title": "Dependency Ticket",
            "description": "Will be completed",
            "acceptance_criteria": [],
            "priority": 1,
        },
    )
    dep_id = resp.json()["id"]
    await client.patch(f"/api/tickets/{dep_id}", json={"state": "done"})

    # Add dependency
    await client.post(
        f"/api/tickets/{ticket_id}/dependencies",
        json={"depends_on_ticket_id": dep_id},
    )

    # Transition should succeed
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "in_progress", "agent_id": "agent-1"},
        )
    assert resp.status_code == 200
    assert resp.json()["state"] == "in_progress"


# --- Auto-generated note tests ---


@pytest.mark.anyio
async def test_transition_auto_generates_note(
    client: AsyncClient, ticket_id: int
) -> None:
    """Every state transition auto-generates a note."""
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "in_progress", "agent_id": "agent-1"},
        )

    resp = await client.get(f"/api/tickets/{ticket_id}/notes")
    assert resp.status_code == 200
    notes = resp.json()
    assert len(notes) >= 1
    note = notes[0]
    assert "to_do" in note["content"]
    assert "in_progress" in note["content"]
    assert note["note_type"] == "progress"


@pytest.mark.anyio
async def test_transition_with_custom_note(
    client: AsyncClient, ticket_id: int
) -> None:
    """Transition with a note field includes it in the auto-generated note."""
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={
                "new_state": "in_progress",
                "agent_id": "agent-1",
                "note": "Starting development work",
            },
        )

    resp = await client.get(f"/api/tickets/{ticket_id}/notes")
    notes = resp.json()
    assert len(notes) >= 1
    # Check that the custom note content is present
    note_contents = " ".join(n["content"] for n in notes)
    assert "Starting development work" in note_contents


# --- Redis event publishing tests ---


@pytest.mark.anyio
async def test_transition_publishes_redis_event(
    client: AsyncClient, ticket_id: int
) -> None:
    """State transition publishes state_change event to Redis."""
    mock_publish = AsyncMock()
    with patch("app.routers.transitions.publish_event", mock_publish):
        await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "in_progress", "agent_id": "agent-1"},
        )

    mock_publish.assert_called_once()
    call_args = mock_publish.call_args
    assert call_args[0][0] == "ticket:events"
    event_data = call_args[0][1]
    assert event_data["event_type"] == "ticket_state_changed"
    assert event_data["ticket_id"] == ticket_id
    assert event_data["previous_state"] == "to_do"
    assert event_data["new_state"] == "in_progress"
    assert event_data["agent_id"] == "agent-1"
    assert "timestamp" in event_data


# --- Event record tests ---


@pytest.mark.anyio
async def test_transition_creates_event_record(
    client: AsyncClient, ticket_id: int, session: AsyncSession
) -> None:
    """State transition creates an Event record in the database."""
    from sqlalchemy import select

    from app.models import Event

    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "in_progress", "agent_id": "agent-1"},
        )

    result = await session.execute(
        select(Event).where(Event.ticket_id == ticket_id)
    )
    events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].event_type == "ticket_state_changed"
    assert events[0].previous_state == "to_do"
    assert events[0].new_state == "in_progress"
    assert events[0].agent_id == "agent-1"


# --- Edge case tests ---


@pytest.mark.anyio
async def test_transition_nonexistent_ticket(client: AsyncClient) -> None:
    """Transitioning a non-existent ticket returns 404."""
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            "/api/tickets/9999/transition",
            json={"new_state": "in_progress", "agent_id": "agent-1"},
        )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_transition_invalid_state_name(
    client: AsyncClient, ticket_id: int
) -> None:
    """Transitioning to an invalid state returns 400."""
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "invalid_state", "agent_id": "agent-1"},
        )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_transition_same_state(
    client: AsyncClient, ticket_id: int
) -> None:
    """Transitioning to the same state returns 400."""
    with patch("app.routers.transitions.publish_event", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/tickets/{ticket_id}/transition",
            json={"new_state": "to_do", "agent_id": "agent-1"},
        )
    assert resp.status_code == 400
