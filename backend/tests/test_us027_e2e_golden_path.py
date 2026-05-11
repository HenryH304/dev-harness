"""Tests for US-027: End-to-end golden path test.

Verifies the complete agent workflow from import through to done,
including developer pickup/completion, reviewer failure/rejection
threshold → blocked, and merger success → done.
"""

import json
import tempfile
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AgentRegistry, Event, Project, Ticket  # noqa: F401

# ── Fixtures ─────────────────────────────────────────────────────────


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
async def mock_publish():
    """Shared AsyncMock for publish_event — captures all Redis events."""
    return mock.AsyncMock()


@pytest.fixture
async def app(engine, session_factory, mock_publish):
    from app.main import app
    from app.routers.agents import _get_session as _get_session_agents
    from app.routers.dashboard import _get_session as _get_session_dashboard
    from app.routers.dependencies import _get_session as _get_session_deps
    from app.routers.notes import _get_session as _get_session_notes
    from app.routers.projects import _get_session as _get_session_projects
    from app.routers.settings import _get_session as _get_session_settings
    from app.routers.tickets import _get_session as _get_session_tickets
    from app.routers.transitions import _get_session as _get_session_transitions

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[_get_session_agents] = override_session
    app.dependency_overrides[_get_session_dashboard] = override_session
    app.dependency_overrides[_get_session_deps] = override_session
    app.dependency_overrides[_get_session_notes] = override_session
    app.dependency_overrides[_get_session_projects] = override_session
    app.dependency_overrides[_get_session_settings] = override_session
    app.dependency_overrides[_get_session_tickets] = override_session
    app.dependency_overrides[_get_session_transitions] = override_session

    with (
        mock.patch("app.main.init_db"),
        mock.patch("app.main.close_redis"),
        mock.patch("app.main.redis_listener"),
        mock.patch("app.main.notification_listener"),
        mock.patch("app.main.agent_event_listener", new_callable=mock.AsyncMock),
        mock.patch("app.main.heartbeat_loop", new_callable=mock.AsyncMock),
        mock.patch("app.main.startup_scan", new_callable=mock.AsyncMock),
        mock.patch("app.routers.agents.publish_event", mock_publish),
        mock.patch("app.routers.transitions.publish_event", mock_publish),
        mock.patch("app.routers.projects.publish_event", mock_publish),
        mock.patch("app.routers.agents.acquire_lock", return_value=True),
        mock.patch(
            "app.routers.agents.create_worktree",
            return_value={"worktree_path": "/tmp/wt-test", "branch_name": "ticket/test"},
        ),
    ):
        yield app

    app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def sample_prd_file():
    """Create a temporary prd.json file with sample user stories."""
    prd = {
        "project": "test-project",
        "userStories": [
            {
                "id": "TS-001",
                "title": "Implement login",
                "description": "As a user, I want to log in.",
                "acceptanceCriteria": ["Login form renders", "Auth works"],
                "priority": 1,
            },
            {
                "id": "TS-002",
                "title": "Implement dashboard",
                "description": "As a user, I want to see a dashboard.",
                "acceptanceCriteria": ["Dashboard loads"],
                "priority": 2,
            },
        ],
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(prd, f)
        return f.name


# ── Helper to assign an agent to a ticket ────────────────────────────


async def _assign_agent(
    session_factory, ticket_id: int, agent_type: str, agent_id: str
) -> None:
    """Directly set ticket agent and create agent registry entry."""
    async with session_factory() as session:
        import datetime

        result = await session.execute(
            select(Ticket).where(Ticket.id == ticket_id)
        )
        ticket = result.scalar_one()
        from app.routers.agents import PICKUP_NEXT_STATE

        ticket.state = PICKUP_NEXT_STATE[agent_type]
        ticket.current_agent = agent_id
        ticket.assigned_at = datetime.datetime.now(datetime.timezone.utc)
        ticket.agent_attempts += 1

        agent = AgentRegistry(
            agent_type=agent_type,
            status="busy",
            current_ticket_id=ticket_id,
            started_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(agent)
        await session.commit()


# ── E2E Golden Path Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_creates_tickets_in_todo(client, sample_prd_file):
    """Import a sample prd.json and verify tickets are created in to_do."""
    resp = await client.post(
        "/api/projects/import",
        json={"project_name": "e2e-project", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )
    assert resp.status_code == 200
    assert resp.json()["imported_count"] == 2

    # Verify all tickets are in to_do
    resp = await client.get("/api/tickets", params={"project": "e2e-project"})
    assert resp.status_code == 200
    tickets = resp.json()
    assert len(tickets) == 2
    assert all(t["state"] == "to_do" for t in tickets)


@pytest.mark.asyncio
async def test_developer_pickup_moves_to_in_progress(
    client, sample_prd_file, session_factory
):
    """Developer agent pickup moves ticket from to_do to in_progress."""
    # Import tickets
    await client.post(
        "/api/projects/import",
        json={"project_name": "e2e-project", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )

    # Developer picks up highest priority ticket
    resp = await client.post("/api/agents/pickup/developer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "in_progress"
    assert data["current_agent"] is not None
    assert data["agent_attempts"] == 1
    assert data["title"] == "Implement login"  # priority 1


@pytest.mark.asyncio
async def test_developer_completion_moves_to_ready_for_review(
    client, sample_prd_file, session_factory
):
    """Developer completion moves ticket from in_progress to ready_for_review."""
    await client.post(
        "/api/projects/import",
        json={"project_name": "e2e-project", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )
    # Pickup
    pickup_resp = await client.post("/api/agents/pickup/developer")
    ticket_id = pickup_resp.json()["id"]

    # Complete
    resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "ready_for_review"
    assert data["current_agent"] is None


@pytest.mark.asyncio
async def test_reviewer_failure_returns_to_todo_with_note(
    client, sample_prd_file, session_factory
):
    """Reviewer failure returns ticket to to_do with failure note and increments rejection count."""
    # Import and move through developer phase
    await client.post(
        "/api/projects/import",
        json={"project_name": "e2e-project", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )
    pickup_resp = await client.post("/api/agents/pickup/developer")
    ticket_id = pickup_resp.json()["id"]
    await client.post(f"/api/agents/complete/{ticket_id}")

    # Assign reviewer
    await _assign_agent(
        session_factory, ticket_id, "reviewer", "reviewer-e2e001"
    )

    # Reviewer fails
    resp = await client.post(
        f"/api/agents/fail/{ticket_id}",
        json={"reason": "Code quality issues", "suggested_fixes": "Refactor"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "to_do"
    assert data["review_rejection_count"] == 1
    assert data["current_agent"] is None

    # Verify failure note was created
    notes_resp = await client.get(f"/api/tickets/{ticket_id}/notes")
    assert notes_resp.status_code == 200
    notes = notes_resp.json()
    review_notes = [n for n in notes if n["note_type"] in ("failure", "review_rejection")]
    assert len(review_notes) >= 1
    assert "Code quality issues" in review_notes[0]["content"]


@pytest.mark.asyncio
async def test_three_review_rejections_blocks_ticket(
    client, sample_prd_file, session_factory, mock_publish
):
    """Three review rejections move ticket to blocked and trigger alert."""
    # Import and move through developer phase
    await client.post(
        "/api/projects/import",
        json={"project_name": "e2e-project", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )
    pickup_resp = await client.post("/api/agents/pickup/developer")
    ticket_id = pickup_resp.json()["id"]
    await client.post(f"/api/agents/complete/{ticket_id}")

    # Simulate 3 review rejection cycles
    for i in range(3):
        # Assign reviewer
        await _assign_agent(
            session_factory, ticket_id, "reviewer", f"reviewer-rej{i:02d}"
        )

        # Reviewer fails
        resp = await client.post(
            f"/api/agents/fail/{ticket_id}",
            json={"reason": f"Rejection #{i + 1}"},
        )
        assert resp.status_code == 200

        if i < 2:
            # First two rejections return to to_do
            assert resp.json()["state"] == "to_do"
            assert resp.json()["review_rejection_count"] == i + 1
            # Need to move back through developer for next review cycle
            await _assign_agent(
                session_factory, ticket_id, "developer", f"developer-fix{i:02d}"
            )
            await client.post(f"/api/agents/complete/{ticket_id}")
        else:
            # Third rejection moves to blocked
            assert resp.json()["state"] == "blocked"
            assert resp.json()["review_rejection_count"] == 3

    # Verify ticket_blocked event was published
    blocked_events = [
        call
        for call in mock_publish.call_args_list
        if call[0][1].get("event_type") == "ticket_blocked"
    ]
    assert len(blocked_events) >= 1
    blocked_event = blocked_events[0][0][1]
    assert blocked_event["ticket_id"] == ticket_id
    assert blocked_event["review_rejection_count"] == 3


@pytest.mark.asyncio
async def test_merger_success_moves_to_done(
    client, sample_prd_file, session_factory
):
    """Merger completion moves ticket from ready_to_merge to done."""
    # Import and move through the full pipeline
    await client.post(
        "/api/projects/import",
        json={"project_name": "e2e-project", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )
    pickup_resp = await client.post("/api/agents/pickup/developer")
    ticket_id = pickup_resp.json()["id"]

    # Developer completes → ready_for_review
    await client.post(f"/api/agents/complete/{ticket_id}")

    # Reviewer picks up and completes → ready_for_test
    await _assign_agent(
        session_factory, ticket_id, "reviewer", "reviewer-ok001"
    )
    await client.post(f"/api/agents/complete/{ticket_id}")

    # Tester picks up and completes → ready_to_merge
    await _assign_agent(
        session_factory, ticket_id, "tester", "tester-ok001"
    )
    await client.post(f"/api/agents/complete/{ticket_id}")

    # Merger picks up and completes → done
    await _assign_agent(
        session_factory, ticket_id, "merger", "merger-ok001"
    )
    resp = await client.post(f"/api/agents/complete/{ticket_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "done"
    assert data["current_agent"] is None


@pytest.mark.asyncio
async def test_full_golden_path_end_to_end(
    client, sample_prd_file, session_factory, mock_publish
):
    """Full golden path: import → developer → reviewer fail → 3 rejections
    → blocked → second ticket goes all the way to done.
    Verifies the complete workflow with event publishing at each step.
    """
    mock_publish.reset_mock()

    # 1. Import project
    resp = await client.post(
        "/api/projects/import",
        json={"project_name": "golden", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )
    assert resp.status_code == 200
    assert resp.json()["imported_count"] == 2

    # Verify tickets in to_do
    tickets_resp = await client.get(
        "/api/tickets", params={"project": "golden"}
    )
    tickets = tickets_resp.json()
    assert len(tickets) == 2
    ticket_ids = sorted([t["id"] for t in tickets])
    ticket_a_id = ticket_ids[0]  # priority 1
    ticket_b_id = ticket_ids[1]  # priority 2

    # 2. Developer picks up ticket A (priority 1)
    pickup_resp = await client.post("/api/agents/pickup/developer")
    assert pickup_resp.status_code == 200
    assert pickup_resp.json()["id"] == ticket_a_id
    assert pickup_resp.json()["state"] == "in_progress"

    # 3. Developer completes ticket A → ready_for_review
    resp = await client.post(f"/api/agents/complete/{ticket_a_id}")
    assert resp.json()["state"] == "ready_for_review"

    # 4. First reviewer rejects → back to to_do, rejection_count = 1
    await _assign_agent(
        session_factory, ticket_a_id, "reviewer", "reviewer-r01"
    )
    resp = await client.post(
        f"/api/agents/fail/{ticket_a_id}",
        json={"reason": "Needs tests"},
    )
    assert resp.json()["state"] == "to_do"
    assert resp.json()["review_rejection_count"] == 1

    # 5. Developer fixes, reviewer rejects again → rejection_count = 2
    await _assign_agent(
        session_factory, ticket_a_id, "developer", "developer-fix01"
    )
    await client.post(f"/api/agents/complete/{ticket_a_id}")
    await _assign_agent(
        session_factory, ticket_a_id, "reviewer", "reviewer-r02"
    )
    resp = await client.post(
        f"/api/agents/fail/{ticket_a_id}",
        json={"reason": "Still failing"},
    )
    assert resp.json()["state"] == "to_do"
    assert resp.json()["review_rejection_count"] == 2

    # 6. Developer fixes, reviewer rejects third time → BLOCKED
    await _assign_agent(
        session_factory, ticket_a_id, "developer", "developer-fix02"
    )
    await client.post(f"/api/agents/complete/{ticket_a_id}")
    await _assign_agent(
        session_factory, ticket_a_id, "reviewer", "reviewer-r03"
    )
    resp = await client.post(
        f"/api/agents/fail/{ticket_a_id}",
        json={"reason": "Fundamentally broken"},
    )
    assert resp.json()["state"] == "blocked"
    assert resp.json()["review_rejection_count"] == 3

    # Verify ticket_blocked event was published
    blocked_events = [
        c
        for c in mock_publish.call_args_list
        if c[0][1].get("event_type") == "ticket_blocked"
    ]
    assert len(blocked_events) == 1
    assert blocked_events[0][0][1]["ticket_id"] == ticket_a_id

    # 7. Meanwhile, ticket B goes through the full happy path
    # Developer pickup
    await _assign_agent(
        session_factory, ticket_b_id, "developer", "developer-b01"
    )
    resp = await client.post(f"/api/agents/complete/{ticket_b_id}")
    assert resp.json()["state"] == "ready_for_review"

    # Reviewer approves
    await _assign_agent(
        session_factory, ticket_b_id, "reviewer", "reviewer-b01"
    )
    resp = await client.post(f"/api/agents/complete/{ticket_b_id}")
    assert resp.json()["state"] == "ready_for_test"

    # Tester passes
    await _assign_agent(
        session_factory, ticket_b_id, "tester", "tester-b01"
    )
    resp = await client.post(f"/api/agents/complete/{ticket_b_id}")
    assert resp.json()["state"] == "ready_to_merge"

    # Merger merges → DONE
    await _assign_agent(
        session_factory, ticket_b_id, "merger", "merger-b01"
    )
    resp = await client.post(f"/api/agents/complete/{ticket_b_id}")
    assert resp.json()["state"] == "done"

    # 8. Verify final board state
    tickets_resp = await client.get(
        "/api/tickets", params={"project": "golden"}
    )
    tickets = {t["id"]: t for t in tickets_resp.json()}
    assert tickets[ticket_a_id]["state"] == "blocked"
    assert tickets[ticket_b_id]["state"] == "done"

    # 9. Verify events were published throughout the workflow
    all_event_types = [
        c[0][1]["event_type"]
        for c in mock_publish.call_args_list
        if isinstance(c[0][1], dict) and "event_type" in c[0][1]
    ]
    assert "agent_assigned" in all_event_types
    assert "agent_completed" in all_event_types
    assert "agent_failed" in all_event_types
    assert "ticket_blocked" in all_event_types


@pytest.mark.asyncio
async def test_websocket_manager_broadcasts_state_changes(app):
    """WebSocket manager broadcasts state change events to connected clients."""
    from app.websocket import manager

    # Create mock WebSocket connections
    ws1 = mock.AsyncMock()
    ws2 = mock.AsyncMock()
    manager.active_connections.append(ws1)
    manager.active_connections.append(ws2)

    try:
        event = {
            "event_type": "ticket_state_changed",
            "ticket_id": 1,
            "previous_state": "to_do",
            "new_state": "in_progress",
        }
        await manager.broadcast(event)

        # Both clients should receive the JSON-serialized broadcast
        expected = json.dumps(event)
        ws1.send_text.assert_called_once_with(expected)
        ws2.send_text.assert_called_once_with(expected)
    finally:
        manager.active_connections.clear()


@pytest.mark.asyncio
async def test_websocket_endpoint_connects(app):
    """WebSocket endpoint at /ws accepts connections."""
    from starlette.testclient import TestClient

    from app.websocket import manager

    manager.active_connections.clear()
    with TestClient(app) as sync_client:
        with sync_client.websocket_connect("/ws"):
            assert len(manager.active_connections) >= 1
        assert len(manager.active_connections) == 0


@pytest.mark.asyncio
async def test_state_transitions_generate_events_in_db(
    client, sample_prd_file, session_factory
):
    """State transitions via the transition endpoint create Event records."""
    await client.post(
        "/api/projects/import",
        json={"project_name": "evt-project", "prd_path": sample_prd_file, "repo_path": "/tmp"},
    )

    # Get ticket ID
    tickets_resp = await client.get(
        "/api/tickets", params={"project": "evt-project"}
    )
    ticket_id = tickets_resp.json()[0]["id"]

    # Transition via the transitions endpoint (manual override)
    resp = await client.post(
        f"/api/tickets/{ticket_id}/transition",
        json={
            "new_state": "in_progress",
            "agent_id": "manual-user",
            "note": "Starting work",
        },
    )
    assert resp.status_code == 200

    # Verify Event record was created in DB
    async with session_factory() as session:
        result = await session.execute(
            select(Event).where(Event.ticket_id == ticket_id)
        )
        events = list(result.scalars().all())
        assert len(events) >= 1
        event = events[0]
        assert event.event_type == "ticket_state_changed"
        assert event.previous_state == "to_do"
        assert event.new_state == "in_progress"

    # Verify auto-generated note
    notes_resp = await client.get(f"/api/tickets/{ticket_id}/notes")
    notes = notes_resp.json()
    transition_notes = [
        n for n in notes if "to_do" in n["content"] and "in_progress" in n["content"]
    ]
    assert len(transition_notes) >= 1
