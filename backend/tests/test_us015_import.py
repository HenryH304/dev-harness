"""Tests for US-015: Ralph prd.json import API."""

import json
import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401 — registers all ORM mappers with Base.metadata


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as sess:
        yield sess


@pytest.fixture
async def app(engine):
    from unittest import mock

    from app.main import app as fastapi_app
    from app.routers.projects import _get_session as projects_get_session
    from app.routers.tickets import _get_session as tickets_get_session

    async def override_session():
        async_session = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session() as sess:
            yield sess

    fastapi_app.dependency_overrides[projects_get_session] = override_session
    fastapi_app.dependency_overrides[tickets_get_session] = override_session

    with (
        mock.patch("app.main.init_db"),
        mock.patch("app.main.close_redis"),
        mock.patch("app.main.redis_listener"),
        mock.patch("app.routers.projects.publish_event", new_callable=mock.AsyncMock),
    ):
        yield fastapi_app

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_prd():
    """Create a sample prd.json file and return its path."""
    prd = {
        "project": "TestProject",
        "branchName": "feature/test",
        "description": "A test project",
        "userStories": [
            {
                "id": "US-001",
                "title": "First story",
                "description": "Do the first thing",
                "acceptanceCriteria": ["AC1", "AC2"],
                "priority": 1,
                "passes": False,
                "notes": "",
            },
            {
                "id": "US-002",
                "title": "Second story",
                "description": "Do the second thing",
                "acceptanceCriteria": ["AC3"],
                "priority": 2,
                "passes": True,
                "notes": "Already done",
            },
            {
                "id": "US-003",
                "title": "Third story",
                "description": "Do the third thing",
                "acceptanceCriteria": ["AC4", "AC5", "AC6"],
                "priority": 3,
                "passes": False,
                "notes": "",
            },
        ],
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(prd, f)
        f.flush()
        yield f.name
    os.unlink(f.name)


# --- Unit tests for import endpoint ---


@pytest.mark.asyncio
async def test_import_creates_tickets(client, sample_prd):
    """POST /api/projects/import creates tickets from prd.json."""
    resp = await client.post(
        "/api/projects/import",
        json={"project_name": "my-project", "prd_path": sample_prd, "repo_path": "/tmp"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported_count"] == 3


@pytest.mark.asyncio
async def test_import_maps_fields_correctly(client, sample_prd):
    """Imported tickets have correct field mapping from Ralph prd.json."""
    await client.post(
        "/api/projects/import",
        json={"project_name": "my-project", "prd_path": sample_prd, "repo_path": "/tmp"},
    )
    # Fetch all tickets
    resp = await client.get("/api/tickets", params={"project": "my-project"})
    tickets = resp.json()
    assert len(tickets) == 3

    # Check first ticket mapping
    t1 = next(t for t in tickets if t["title"] == "First story")
    assert t1["project"] == "my-project"
    assert t1["description"] == "Do the first thing"
    assert t1["acceptance_criteria"] == ["AC1", "AC2"]
    assert t1["priority"] == 1


@pytest.mark.asyncio
async def test_import_all_tickets_start_in_to_do(client, sample_prd):
    """All imported tickets start in to_do state regardless of passes field."""
    await client.post(
        "/api/projects/import",
        json={"project_name": "my-project", "prd_path": sample_prd, "repo_path": "/tmp"},
    )
    resp = await client.get("/api/tickets", params={"project": "my-project"})
    tickets = resp.json()
    for ticket in tickets:
        assert ticket["state"] == "to_do"


@pytest.mark.asyncio
async def test_import_sets_project_name(client, sample_prd):
    """Project field is set to project_name from request, not from prd.json."""
    await client.post(
        "/api/projects/import",
        json={"project_name": "custom-name", "prd_path": sample_prd, "repo_path": "/tmp"},
    )
    resp = await client.get("/api/tickets", params={"project": "custom-name"})
    tickets = resp.json()
    assert len(tickets) == 3
    for ticket in tickets:
        assert ticket["project"] == "custom-name"


@pytest.mark.asyncio
async def test_import_returns_count(client, sample_prd):
    """Import endpoint returns the count of imported tickets."""
    resp = await client.post(
        "/api/projects/import",
        json={"project_name": "my-project", "prd_path": sample_prd, "repo_path": "/tmp"},
    )
    assert resp.status_code == 200
    assert resp.json()["imported_count"] == 3


@pytest.mark.asyncio
async def test_import_nonexistent_file(client):
    """Import with nonexistent prd_path returns 400."""
    resp = await client.post(
        "/api/projects/import",
        json={"project_name": "my-project", "prd_path": "/nonexistent/prd.json", "repo_path": "/tmp"},
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower() or "error" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_import_invalid_json(client):
    """Import with invalid JSON file returns 400."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write("not valid json {{{")
        f.flush()
        path = f.name

    try:
        resp = await client.post(
            "/api/projects/import",
            json={"project_name": "my-project", "prd_path": path, "repo_path": "/tmp"},
        )
        assert resp.status_code == 400
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_import_missing_user_stories(client):
    """Import with prd.json missing userStories key returns 400."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump({"project": "test"}, f)
        f.flush()
        path = f.name

    try:
        resp = await client.post(
            "/api/projects/import",
            json={"project_name": "my-project", "prd_path": path, "repo_path": "/tmp"},
        )
        assert resp.status_code == 400
        assert "userStories" in resp.json()["detail"]
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_import_empty_stories(client):
    """Import with empty userStories array creates no tickets."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump({"userStories": []}, f)
        f.flush()
        path = f.name

    try:
        resp = await client.post(
            "/api/projects/import",
            json={"project_name": "my-project", "prd_path": path, "repo_path": "/tmp"},
        )
        assert resp.status_code == 200
        assert resp.json()["imported_count"] == 0
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_import_preserves_priority_ordering(client, sample_prd):
    """Imported tickets preserve priority from prd.json."""
    await client.post(
        "/api/projects/import",
        json={"project_name": "my-project", "prd_path": sample_prd, "repo_path": "/tmp"},
    )
    resp = await client.get("/api/tickets", params={"project": "my-project"})
    tickets = resp.json()
    priorities = sorted([t["priority"] for t in tickets])
    assert priorities == [1, 2, 3]
