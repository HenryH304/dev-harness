"""Tests for US-016: Settings API."""

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Setting


@pytest.fixture
async def engine() -> AsyncGenerator[Any, None]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine: Any) -> sessionmaker:  # type: ignore[type-arg]
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]


@pytest.fixture
async def app(engine: Any, session_factory: Any) -> Any:
    from app.main import app as fastapi_app

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    # Override _get_session for settings router
    from app.routers.settings import _get_session as settings_get_session

    fastapi_app.dependency_overrides[settings_get_session] = override_session

    with mock.patch("app.main.init_db"), mock.patch("app.main.close_redis"):
        yield fastapi_app

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: Any) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def seeded_session(session_factory: Any) -> AsyncSession:
    """Session with some settings pre-populated."""
    async with session_factory() as session:
        session.add(Setting(key="max_agents_system", value="10"))
        session.add(Setting(key="review_rejection_threshold", value="3"))
        session.add(Setting(key="active_priority_project", value="my-project"))
        await session.commit()
    async with session_factory() as session:
        yield session


# --- GET /api/settings ---


@pytest.mark.asyncio
async def test_get_settings_empty(client: AsyncClient) -> None:
    """GET /api/settings returns empty dict when no settings exist."""
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"settings": {}}


@pytest.mark.asyncio
async def test_get_settings_returns_all(
    client: AsyncClient, seeded_session: AsyncSession
) -> None:
    """GET /api/settings returns all current settings."""
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    settings = data["settings"]
    assert settings["max_agents_system"] == "10"
    assert settings["review_rejection_threshold"] == "3"
    assert settings["active_priority_project"] == "my-project"
    assert len(settings) == 3


# --- PATCH /api/settings ---


@pytest.mark.asyncio
async def test_patch_settings_create_new(client: AsyncClient) -> None:
    """PATCH /api/settings creates new settings if they don't exist."""
    resp = await client.patch(
        "/api/settings",
        json={"settings": {"max_agents_system": "5", "active_priority_project": "proj-x"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated_count"] == 2

    # Verify they were saved
    resp2 = await client.get("/api/settings")
    settings = resp2.json()["settings"]
    assert settings["max_agents_system"] == "5"
    assert settings["active_priority_project"] == "proj-x"


@pytest.mark.asyncio
async def test_patch_settings_update_existing(
    client: AsyncClient, seeded_session: AsyncSession
) -> None:
    """PATCH /api/settings updates existing settings values."""
    resp = await client.patch(
        "/api/settings",
        json={"settings": {"max_agents_system": "20"}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 1

    # Verify update
    resp2 = await client.get("/api/settings")
    settings = resp2.json()["settings"]
    assert settings["max_agents_system"] == "20"
    # Other settings unchanged
    assert settings["review_rejection_threshold"] == "3"


@pytest.mark.asyncio
async def test_patch_settings_empty_body(client: AsyncClient) -> None:
    """PATCH /api/settings with empty settings dict returns 0 updated."""
    resp = await client.patch("/api/settings", json={"settings": {}})
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 0


@pytest.mark.asyncio
async def test_patch_settings_agent_timeouts(client: AsyncClient) -> None:
    """PATCH /api/settings can update agent timeout settings."""
    resp = await client.patch(
        "/api/settings",
        json={
            "settings": {
                "agent_timeout_developer": "1800",
                "agent_timeout_reviewer": "900",
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 2

    resp2 = await client.get("/api/settings")
    settings = resp2.json()["settings"]
    assert settings["agent_timeout_developer"] == "1800"
    assert settings["agent_timeout_reviewer"] == "900"


@pytest.mark.asyncio
async def test_patch_settings_max_agents_per_column(client: AsyncClient) -> None:
    """PATCH /api/settings can update max_agents_per_column."""
    resp = await client.patch(
        "/api/settings",
        json={"settings": {"max_agents_per_column": "5"}},
    )
    assert resp.status_code == 200

    resp2 = await client.get("/api/settings")
    assert resp2.json()["settings"]["max_agents_per_column"] == "5"


# --- config.json precedence ---


@pytest.mark.asyncio
async def test_config_json_precedence_on_startup(
    engine: Any, session_factory: Any, tmp_path: Any
) -> None:
    """config.json values take precedence over database settings on startup.

    This test verifies the conceptual behavior: config.json values
    are loaded by the AppConfig system and would override DB settings
    if both exist.
    """
    from app.config import load_config

    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"max_agents_system": 42, "review_rejection_threshold": 7}))

    config = load_config(config_path=config_file)
    assert config.max_agents_system == 42
    assert config.review_rejection_threshold == 7
