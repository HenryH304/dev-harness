"""Tests for US-004: Ticket CRUD API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.database import init_db
from app.main import app
from app.models import Note
from app.routers.tickets import _get_session


@pytest.fixture
async def engine() -> AsyncEngine:
    """Create an in-memory SQLite engine for testing."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(eng)
    return eng


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncSession:
    """Yield an async session for testing."""
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncClient:
    """Create a test client with overridden DB session."""

    async def override_get_session() -> AsyncSession:  # type: ignore[misc]
        async with AsyncSession(engine, expire_on_commit=False) as sess:
            yield sess  # type: ignore[misc]

    app.dependency_overrides[_get_session] = override_get_session
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


VALID_TICKET = {
    "project": "test-project",
    "title": "Test ticket",
    "description": "A test ticket description",
    "acceptance_criteria": ["criterion 1", "criterion 2"],
    "priority": 1,
}


# --- POST /api/tickets ---


class TestCreateTicket:
    async def test_create_ticket_success(self, client: AsyncClient) -> None:
        resp = await client.post("/api/tickets", json=VALID_TICKET)
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"] == "test-project"
        assert data["title"] == "Test ticket"
        assert data["description"] == "A test ticket description"
        assert data["acceptance_criteria"] == ["criterion 1", "criterion 2"]
        assert data["priority"] == 1
        assert data["state"] == "to_do"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_ticket_missing_required_field(self, client: AsyncClient) -> None:
        incomplete = {"project": "test", "title": "Missing fields"}
        resp = await client.post("/api/tickets", json=incomplete)
        assert resp.status_code == 422

    async def test_create_ticket_defaults(self, client: AsyncClient) -> None:
        resp = await client.post("/api/tickets", json=VALID_TICKET)
        data = resp.json()
        assert data["branch_name"] is None
        assert data["worktree_path"] is None
        assert data["current_agent"] is None
        assert data["agent_attempts"] == 0
        assert data["review_rejection_count"] == 0


# --- GET /api/tickets ---


class TestListTickets:
    async def test_list_tickets_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/tickets")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_tickets_returns_all(self, client: AsyncClient) -> None:
        await client.post("/api/tickets", json=VALID_TICKET)
        await client.post(
            "/api/tickets",
            json={**VALID_TICKET, "title": "Second ticket", "project": "other-project"},
        )
        resp = await client.get("/api/tickets")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_tickets_filter_by_project(self, client: AsyncClient) -> None:
        await client.post("/api/tickets", json=VALID_TICKET)
        await client.post(
            "/api/tickets",
            json={**VALID_TICKET, "title": "Other", "project": "other-project"},
        )
        resp = await client.get("/api/tickets", params={"project": "test-project"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["project"] == "test-project"

    async def test_list_tickets_filter_by_state(self, client: AsyncClient) -> None:
        await client.post("/api/tickets", json=VALID_TICKET)
        resp = await client.get("/api/tickets", params={"state": "in_progress"})
        assert resp.status_code == 200
        assert len(resp.json()) == 0

        resp = await client.get("/api/tickets", params={"state": "to_do"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_tickets_filter_by_project_and_state(
        self, client: AsyncClient
    ) -> None:
        await client.post("/api/tickets", json=VALID_TICKET)
        await client.post(
            "/api/tickets",
            json={**VALID_TICKET, "title": "Other", "project": "other-project"},
        )
        resp = await client.get(
            "/api/tickets", params={"project": "test-project", "state": "to_do"}
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# --- GET /api/tickets/{id} ---


class TestGetTicket:
    async def test_get_ticket_success(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/tickets", json=VALID_TICKET)
        ticket_id = create_resp.json()["id"]
        resp = await client.get(f"/api/tickets/{ticket_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == ticket_id
        assert data["title"] == "Test ticket"
        assert "notes" in data

    async def test_get_ticket_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/tickets/9999")
        assert resp.status_code == 404

    async def test_get_ticket_with_notes(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        create_resp = await client.post("/api/tickets", json=VALID_TICKET)
        ticket_id = create_resp.json()["id"]
        # Add notes directly via DB
        note = Note(
            ticket_id=ticket_id,
            author="test-agent",
            content="A test note",
            note_type="general",
        )
        session.add(note)
        await session.commit()
        resp = await client.get(f"/api/tickets/{ticket_id}")
        data = resp.json()
        assert len(data["notes"]) == 1
        assert data["notes"][0]["content"] == "A test note"


# --- PATCH /api/tickets/{id} ---


class TestUpdateTicket:
    async def test_update_ticket_title(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/tickets", json=VALID_TICKET)
        ticket_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/tickets/{ticket_id}", json={"title": "Updated title"}
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated title"

    async def test_update_ticket_multiple_fields(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/tickets", json=VALID_TICKET)
        ticket_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/tickets/{ticket_id}",
            json={"title": "New title", "priority": 5, "description": "New desc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "New title"
        assert data["priority"] == 5
        assert data["description"] == "New desc"

    async def test_update_ticket_not_found(self, client: AsyncClient) -> None:
        resp = await client.patch("/api/tickets/9999", json={"title": "Nope"})
        assert resp.status_code == 404

    async def test_update_ticket_no_fields(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/tickets", json=VALID_TICKET)
        ticket_id = create_resp.json()["id"]
        resp = await client.patch(f"/api/tickets/{ticket_id}", json={})
        assert resp.status_code == 200


# --- DELETE /api/tickets/{id} ---


class TestDeleteTicket:
    async def test_delete_ticket_success(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/tickets", json=VALID_TICKET)
        ticket_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/tickets/{ticket_id}")
        assert resp.status_code == 200
        # Verify it's gone
        get_resp = await client.get(f"/api/tickets/{ticket_id}")
        assert get_resp.status_code == 404

    async def test_delete_ticket_not_found(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/tickets/9999")
        assert resp.status_code == 404


# --- Consistent JSON schema ---


class TestResponseSchema:
    async def test_create_response_has_all_fields(self, client: AsyncClient) -> None:
        resp = await client.post("/api/tickets", json=VALID_TICKET)
        data = resp.json()
        expected_fields = {
            "id", "project", "title", "description", "acceptance_criteria",
            "priority", "state", "branch_name", "worktree_path", "current_agent",
            "assigned_at", "agent_attempts", "developer_timeouts", "reviewer_timeouts",
            "tester_timeouts", "merger_timeouts", "review_rejection_count",
            "created_at", "updated_at",
        }
        assert expected_fields.issubset(set(data.keys()))

    async def test_list_response_items_have_consistent_schema(
        self, client: AsyncClient
    ) -> None:
        await client.post("/api/tickets", json=VALID_TICKET)
        await client.post("/api/tickets", json={**VALID_TICKET, "title": "Second"})
        resp = await client.get("/api/tickets")
        data = resp.json()
        keys_first = set(data[0].keys())
        keys_second = set(data[1].keys())
        assert keys_first == keys_second

    async def test_get_detail_response_includes_notes(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/tickets", json=VALID_TICKET)
        ticket_id = create_resp.json()["id"]
        resp = await client.get(f"/api/tickets/{ticket_id}")
        data = resp.json()
        assert "notes" in data
