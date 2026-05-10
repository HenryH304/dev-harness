"""Tests for /api/features endpoints."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models
from app.database import Base


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def app_fixture(engine):
    from app.main import app as fastapi_app
    from app.routers.features import _get_session as features_get_session

    async def override_session():
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as sess:
            yield sess

    fastapi_app.dependency_overrides[features_get_session] = override_session

    with (
        mock.patch("app.main.init_db"),
        mock.patch("app.main.close_redis"),
        mock.patch("app.main.redis_listener"),
        mock.patch("app.main.notification_listener"),
        mock.patch("app.main.agent_event_listener", new_callable=mock.AsyncMock),
        mock.patch("app.main.heartbeat_loop", new_callable=mock.AsyncMock),
        mock.patch("app.main.startup_scan", new_callable=mock.AsyncMock),
    ):
        yield fastapi_app

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def client(app_fixture):
    transport = ASGITransport(app=app_fixture)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_generate_returns_pending_request(client):
    with mock.patch("app.routers.features._run_generation", new_callable=mock.AsyncMock):
        resp = await client.post(
            "/api/features/generate",
            json={"project": "my-project", "description": "Add login"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["project"] == "my-project"
    assert data["description"] == "Add login"
    assert data["id"] > 0


@pytest.mark.asyncio
async def test_list_feature_requests_empty(client):
    resp = await client.get("/api/features")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_feature_requests_returns_created(client):
    with mock.patch("app.routers.features._run_generation", new_callable=mock.AsyncMock):
        await client.post(
            "/api/features/generate",
            json={"project": "proj", "description": "Feature A"},
        )
        await client.post(
            "/api/features/generate",
            json={"project": "proj", "description": "Feature B"},
        )

    resp = await client.get("/api/features")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_feature_request_by_id(client):
    with mock.patch("app.routers.features._run_generation", new_callable=mock.AsyncMock):
        create_resp = await client.post(
            "/api/features/generate",
            json={"project": "p", "description": "d"},
        )
    feature_id = create_resp.json()["id"]

    resp = await client.get(f"/api/features/{feature_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == feature_id


@pytest.mark.asyncio
async def test_get_feature_request_not_found(client):
    resp = await client.get("/api/features/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_stories_creates_tickets(engine):
    from sqlalchemy import select
    from app.routers.features import _import_stories
    from app.models import Ticket, TicketDependency

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    stories = [
        {"id": "US-001", "title": "First", "description": "desc", "acceptanceCriteria": ["AC1"], "priority": 1, "dependencies": []},
        {"id": "US-002", "title": "Second", "description": "desc2", "acceptanceCriteria": [], "priority": 2, "dependencies": ["US-001"]},
    ]
    async with async_session() as session:
        count = await _import_stories(session, "my-proj", stories)
        await session.commit()

    assert count == 2

    async with async_session() as session:
        tickets = (await session.execute(select(Ticket))).scalars().all()
        assert len(tickets) == 2
        assert tickets[0].title == "First"
        assert tickets[1].title == "Second"

        deps = (await session.execute(select(TicketDependency))).scalars().all()
        assert len(deps) == 1
        assert deps[0].ticket_id == tickets[1].id
        assert deps[0].depends_on_ticket_id == tickets[0].id
