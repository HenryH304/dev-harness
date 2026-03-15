"""Tests for US-006: Notes and comments API."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.main import app
from app.routers.notes import _get_session as notes_get_session
from app.routers.tickets import _get_session as tickets_get_session


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
    """Create a ticket and return its ID."""
    resp = await client.post(
        "/api/tickets",
        json={
            "project": "test-project",
            "title": "Test Ticket",
            "description": "A ticket for testing notes",
            "acceptance_criteria": ["AC1", "AC2"],
            "priority": 1,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# --- Unit tests: Note creation ---


@pytest.mark.anyio
async def test_create_note(client: AsyncClient, ticket_id: int) -> None:
    """POST /api/tickets/{id}/notes creates a note."""
    resp = await client.post(
        f"/api/tickets/{ticket_id}/notes",
        json={
            "author": "developer-1",
            "content": "Started working on this.",
            "note_type": "progress",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticket_id"] == ticket_id
    assert data["author"] == "developer-1"
    assert data["content"] == "Started working on this."
    assert data["note_type"] == "progress"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.anyio
async def test_create_note_all_types(client: AsyncClient, ticket_id: int) -> None:
    """Notes support all valid note types."""
    for note_type in ["progress", "failure", "review", "test_result", "general"]:
        resp = await client.post(
            f"/api/tickets/{ticket_id}/notes",
            json={"author": "agent", "content": f"Note type: {note_type}", "note_type": note_type},
        )
        assert resp.status_code == 201
        assert resp.json()["note_type"] == note_type


@pytest.mark.anyio
async def test_create_note_markdown_content(client: AsyncClient, ticket_id: int) -> None:
    """Note content supports plain text including markdown."""
    markdown = "## Heading\n\n- bullet 1\n- bullet 2\n\n```python\nprint('hello')\n```"
    resp = await client.post(
        f"/api/tickets/{ticket_id}/notes",
        json={"author": "developer", "content": markdown, "note_type": "general"},
    )
    assert resp.status_code == 201
    assert resp.json()["content"] == markdown


@pytest.mark.anyio
async def test_create_note_nonexistent_ticket(client: AsyncClient) -> None:
    """Creating a note for a non-existent ticket returns 404."""
    resp = await client.post(
        "/api/tickets/9999/notes",
        json={"author": "agent", "content": "test", "note_type": "general"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_note_missing_fields(client: AsyncClient, ticket_id: int) -> None:
    """Creating a note without required fields returns 422."""
    resp = await client.post(
        f"/api/tickets/{ticket_id}/notes",
        json={"author": "agent"},
    )
    assert resp.status_code == 422


# --- Unit tests: Note retrieval ---


@pytest.mark.anyio
async def test_get_notes_empty(client: AsyncClient, ticket_id: int) -> None:
    """GET /api/tickets/{id}/notes returns empty list for ticket with no notes."""
    resp = await client.get(f"/api/tickets/{ticket_id}/notes")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_get_notes_ordered_desc(client: AsyncClient, ticket_id: int) -> None:
    """GET /api/tickets/{id}/notes returns notes ordered by created_at descending."""
    # Create notes with slight delays to ensure different timestamps
    for i in range(3):
        await client.post(
            f"/api/tickets/{ticket_id}/notes",
            json={"author": f"agent-{i}", "content": f"Note {i}", "note_type": "progress"},
        )
        if i < 2:
            await asyncio.sleep(0.05)  # small delay for timestamp ordering

    resp = await client.get(f"/api/tickets/{ticket_id}/notes")
    assert resp.status_code == 200
    notes = resp.json()
    assert len(notes) == 3
    # Most recent first
    assert notes[0]["content"] == "Note 2"
    assert notes[1]["content"] == "Note 1"
    assert notes[2]["content"] == "Note 0"


@pytest.mark.anyio
async def test_get_notes_nonexistent_ticket(client: AsyncClient) -> None:
    """GET /api/tickets/{id}/notes for non-existent ticket returns 404."""
    resp = await client.get("/api/tickets/9999/notes")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_notes_isolated_per_ticket(client: AsyncClient, ticket_id: int) -> None:
    """Notes are scoped to their ticket — not visible on other tickets."""
    # Create a second ticket
    resp = await client.post(
        "/api/tickets",
        json={
            "project": "test-project",
            "title": "Other Ticket",
            "description": "Another ticket",
            "acceptance_criteria": [],
            "priority": 2,
        },
    )
    other_id = resp.json()["id"]

    # Add note to first ticket
    await client.post(
        f"/api/tickets/{ticket_id}/notes",
        json={"author": "agent", "content": "Only for ticket 1", "note_type": "general"},
    )

    # Second ticket should have no notes
    resp = await client.get(f"/api/tickets/{other_id}/notes")
    assert resp.status_code == 200
    assert resp.json() == []


# --- E2E golden path test ---


@pytest.mark.anyio
async def test_e2e_create_ticket_add_notes_verify_order(client: AsyncClient) -> None:
    """Golden path: create ticket, add 3 notes, verify order."""
    # Step 1: Create a ticket
    resp = await client.post(
        "/api/tickets",
        json={
            "project": "e2e-project",
            "title": "E2E Ticket",
            "description": "Testing the full notes flow",
            "acceptance_criteria": ["Notes work"],
            "priority": 1,
        },
    )
    assert resp.status_code == 201
    tid = resp.json()["id"]

    # Step 2: Add 3 notes with different types
    note_data = [
        {
            "author": "developer-1",
            "content": "Started implementation",
            "note_type": "progress",
        },
        {
            "author": "reviewer-1",
            "content": "Code looks **good** but needs tests",
            "note_type": "review",
        },
        {
            "author": "tester-1",
            "content": "All tests passing\n\n- unit: 10/10\n- e2e: 3/3",
            "note_type": "test_result",
        },
    ]
    for nd in note_data:
        await asyncio.sleep(0.05)
        resp = await client.post(f"/api/tickets/{tid}/notes", json=nd)
        assert resp.status_code == 201

    # Step 3: Verify notes returned in reverse chronological order
    resp = await client.get(f"/api/tickets/{tid}/notes")
    assert resp.status_code == 200
    notes = resp.json()
    assert len(notes) == 3
    assert notes[0]["author"] == "tester-1"
    assert notes[1]["author"] == "reviewer-1"
    assert notes[2]["author"] == "developer-1"

    # Step 4: Also verify notes appear in ticket detail
    resp = await client.get(f"/api/tickets/{tid}")
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["notes"]) == 3
    assert detail["notes"][0]["author"] == "tester-1"
