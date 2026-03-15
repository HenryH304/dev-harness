"""Tests for US-005: Ticket dependency management API."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.database import init_db
from app.main import app
from app.routers.dependencies import _get_session


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
    from app.routers.tickets import _get_session as tickets_get_session

    async def override_get_session() -> AsyncSession:  # type: ignore[misc]
        async with AsyncSession(engine, expire_on_commit=False) as sess:
            yield sess  # type: ignore[misc]

    app.dependency_overrides[_get_session] = override_get_session
    app.dependency_overrides[tickets_get_session] = override_get_session
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


VALID_TICKET = {
    "project": "test-project",
    "title": "Test ticket",
    "description": "A test ticket description",
    "acceptance_criteria": ["criterion 1"],
    "priority": 1,
}


async def _create_ticket(client: AsyncClient, **overrides: str | int) -> int:
    """Helper to create a ticket and return its id."""
    data = {**VALID_TICKET, **overrides}
    resp = await client.post("/api/tickets", json=data)
    assert resp.status_code == 201
    return resp.json()["id"]


# --- POST /api/tickets/{id}/dependencies ---


class TestAddDependency:
    async def test_add_dependency_success(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        resp = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticket_id"] == ticket_a
        assert data["depends_on_ticket_id"] == ticket_b
        assert "id" in data
        assert "created_at" in data

    async def test_add_dependency_ticket_not_found(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        resp = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": 9999},
        )
        assert resp.status_code == 404

    async def test_add_dependency_parent_ticket_not_found(
        self, client: AsyncClient
    ) -> None:
        ticket_b = await _create_ticket(client, title="Ticket B")
        resp = await client.post(
            "/api/tickets/9999/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        assert resp.status_code == 404

    async def test_add_dependency_self_reference(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        resp = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_a},
        )
        assert resp.status_code == 400

    async def test_add_duplicate_dependency(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        resp = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        assert resp.status_code == 400


# --- Cycle detection ---


class TestCycleDetection:
    async def test_direct_cycle_detected(self, client: AsyncClient) -> None:
        """A -> B, then B -> A should be rejected."""
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        resp1 = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/api/tickets/{ticket_b}/dependencies",
            json={"depends_on_ticket_id": ticket_a},
        )
        assert resp2.status_code == 400
        assert "circular" in resp2.json()["detail"].lower()

    async def test_indirect_cycle_detected(self, client: AsyncClient) -> None:
        """A -> B -> C, then C -> A should be rejected."""
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        ticket_c = await _create_ticket(client, title="Ticket C")
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        await client.post(
            f"/api/tickets/{ticket_b}/dependencies",
            json={"depends_on_ticket_id": ticket_c},
        )
        resp = await client.post(
            f"/api/tickets/{ticket_c}/dependencies",
            json={"depends_on_ticket_id": ticket_a},
        )
        assert resp.status_code == 400
        assert "circular" in resp.json()["detail"].lower()

    async def test_no_false_positive_cycle(self, client: AsyncClient) -> None:
        """A -> B, A -> C should be allowed (no cycle)."""
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        ticket_c = await _create_ticket(client, title="Ticket C")
        resp1 = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_c},
        )
        assert resp2.status_code == 201


# --- DELETE /api/tickets/{id}/dependencies/{dep_id} ---


class TestDeleteDependency:
    async def test_delete_dependency_success(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        create_resp = await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        dep_id = create_resp.json()["id"]
        resp = await client.delete(
            f"/api/tickets/{ticket_a}/dependencies/{dep_id}"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_delete_dependency_not_found(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        resp = await client.delete(
            f"/api/tickets/{ticket_a}/dependencies/9999"
        )
        assert resp.status_code == 404


# --- GET /api/tickets/{id}/dependencies ---


class TestGetDependencies:
    async def test_get_dependencies_empty(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        resp = await client.get(f"/api/tickets/{ticket_a}/dependencies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked_by"] == []
        assert data["blocks"] == []

    async def test_get_dependencies_blocked_by(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        resp = await client.get(f"/api/tickets/{ticket_a}/dependencies")
        data = resp.json()
        assert len(data["blocked_by"]) == 1
        assert data["blocked_by"][0]["id"] == ticket_b
        assert data["blocks"] == []

    async def test_get_dependencies_blocks(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        resp = await client.get(f"/api/tickets/{ticket_b}/dependencies")
        data = resp.json()
        assert data["blocked_by"] == []
        assert len(data["blocks"]) == 1
        assert data["blocks"][0]["id"] == ticket_a

    async def test_get_dependencies_ticket_not_found(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/api/tickets/9999/dependencies")
        assert resp.status_code == 404

    async def test_get_dependencies_multiple(self, client: AsyncClient) -> None:
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        ticket_c = await _create_ticket(client, title="Ticket C")
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_c},
        )
        resp = await client.get(f"/api/tickets/{ticket_a}/dependencies")
        data = resp.json()
        assert len(data["blocked_by"]) == 2
        blocked_ids = {d["id"] for d in data["blocked_by"]}
        assert blocked_ids == {ticket_b, ticket_c}


# --- Blocked ticket transition prevention ---


class TestBlockedTransitionPrevention:
    async def test_blocked_ticket_cannot_leave_todo(
        self, client: AsyncClient
    ) -> None:
        """A ticket with unresolved dependencies cannot transition past to_do."""
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        # A depends on B (B is in to_do, not done)
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        # Try to move A to in_progress
        resp = await client.patch(
            f"/api/tickets/{ticket_a}",
            json={"state": "in_progress"},
        )
        assert resp.status_code == 400
        assert "dependenc" in resp.json()["detail"].lower()

    async def test_resolved_dependency_allows_transition(
        self, client: AsyncClient
    ) -> None:
        """A ticket with all dependencies in done state can transition."""
        ticket_a = await _create_ticket(client, title="Ticket A")
        ticket_b = await _create_ticket(client, title="Ticket B")
        await client.post(
            f"/api/tickets/{ticket_a}/dependencies",
            json={"depends_on_ticket_id": ticket_b},
        )
        # Move B to done
        await client.patch(f"/api/tickets/{ticket_b}", json={"state": "done"})
        # Now A should be able to transition
        resp = await client.patch(
            f"/api/tickets/{ticket_a}",
            json={"state": "in_progress"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "in_progress"
