"""Tests for US-026: Project management — import and priority."""

import json
import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Ticket


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
    from app.routers.settings import _get_session as settings_get_session
    from app.routers.tickets import _get_session as tickets_get_session

    async def override_session():
        async_session = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session() as sess:
            yield sess

    fastapi_app.dependency_overrides[projects_get_session] = override_session
    fastapi_app.dependency_overrides[tickets_get_session] = override_session
    fastapi_app.dependency_overrides[settings_get_session] = override_session

    with (
        mock.patch("app.main.init_db"),
        mock.patch("app.main.close_redis"),
        mock.patch("app.main.redis_listener"),
    ):
        yield fastapi_app

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def seeded_client(client, session):
    """Client with pre-seeded tickets in multiple projects."""
    # Seed project A with 3 tickets
    for i in range(3):
        session.add(
            Ticket(
                project="project-alpha",
                title=f"Alpha ticket {i + 1}",
                description=f"Description {i + 1}",
                acceptance_criteria=[],
                priority=i + 1,
                state="to_do",
            )
        )
    # Seed project B with 2 tickets (one done)
    session.add(
        Ticket(
            project="project-beta",
            title="Beta ticket 1",
            description="Desc",
            acceptance_criteria=[],
            priority=1,
            state="to_do",
        )
    )
    session.add(
        Ticket(
            project="project-beta",
            title="Beta ticket 2",
            description="Desc",
            acceptance_criteria=[],
            priority=2,
            state="done",
        )
    )
    await session.commit()
    yield client


# --- GET /api/projects ---


@pytest.mark.asyncio
async def test_list_projects_empty(client):
    """GET /api/projects returns empty list when no tickets exist."""
    resp = await client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data["projects"] == []


@pytest.mark.asyncio
async def test_list_projects_returns_all_projects(seeded_client):
    """GET /api/projects returns all unique projects with ticket counts."""
    resp = await seeded_client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    projects = data["projects"]
    assert len(projects) == 2

    # Sort by name for stable comparison
    projects.sort(key=lambda p: p["name"])
    assert projects[0]["name"] == "project-alpha"
    assert projects[0]["ticket_count"] == 3
    assert projects[1]["name"] == "project-beta"
    assert projects[1]["ticket_count"] == 2


@pytest.mark.asyncio
async def test_list_projects_includes_active_priority(seeded_client):
    """GET /api/projects includes which project is the active priority."""
    # Set active priority project
    await seeded_client.patch(
        "/api/settings",
        json={"settings": {"active_priority_project": "project-alpha"}},
    )
    resp = await seeded_client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_priority_project"] == "project-alpha"


@pytest.mark.asyncio
async def test_list_projects_active_priority_default_empty(seeded_client):
    """Active priority project defaults to empty string when not set."""
    resp = await seeded_client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_priority_project"] == ""


@pytest.mark.asyncio
async def test_set_active_priority_project(seeded_client):
    """PATCH /api/settings can set active_priority_project."""
    resp = await seeded_client.patch(
        "/api/settings",
        json={"settings": {"active_priority_project": "project-beta"}},
    )
    assert resp.status_code == 200

    # Verify via projects list
    resp = await seeded_client.get("/api/projects")
    data = resp.json()
    assert data["active_priority_project"] == "project-beta"


@pytest.mark.asyncio
async def test_import_then_list_project(client):
    """Import a project then verify it appears in the project list."""
    prd = {
        "userStories": [
            {
                "title": "Story 1",
                "description": "Desc",
                "acceptanceCriteria": [],
                "priority": 1,
            },
            {
                "title": "Story 2",
                "description": "Desc",
                "acceptanceCriteria": [],
                "priority": 2,
            },
        ],
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(prd, f)
        f.flush()
        path = f.name

    try:
        # Import
        resp = await client.post(
            "/api/projects/import",
            json={"project_name": "new-project", "prd_path": path, "repo_path": "/tmp"},
        )
        assert resp.status_code == 200
        assert resp.json()["imported_count"] == 2

        # List
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        projects = resp.json()["projects"]
        assert len(projects) == 1
        assert projects[0]["name"] == "new-project"
        assert projects[0]["ticket_count"] == 2
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_filter_tickets_by_project(seeded_client):
    """GET /api/tickets?project=X returns only that project's tickets."""
    resp = await seeded_client.get(
        "/api/tickets", params={"project": "project-alpha"}
    )
    assert resp.status_code == 200
    tickets = resp.json()
    assert len(tickets) == 3
    for t in tickets:
        assert t["project"] == "project-alpha"
