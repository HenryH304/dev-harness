"""Tests for US-004: Dashboard ColumnCounts model and force-unlock routing."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.main import app
from app.routers.dashboard import ColumnCounts, _get_session as dash_get_session


# --- Unit tests for ColumnCounts model ---


def test_column_counts_has_ready_for_merge_field() -> None:
    """ColumnCounts has ready_for_merge field (not ready_to_merge)."""
    cc = ColumnCounts()
    assert hasattr(cc, "ready_for_merge")
    assert cc.ready_for_merge == 0


def test_column_counts_has_in_merge_field() -> None:
    """ColumnCounts has in_merge field."""
    cc = ColumnCounts()
    assert hasattr(cc, "in_merge")
    assert cc.in_merge == 0


def test_column_counts_no_ready_to_merge_field() -> None:
    """ColumnCounts does not have ready_to_merge field."""
    cc = ColumnCounts()
    assert not hasattr(cc, "ready_to_merge")


# --- Integration tests for /metrics endpoint ---


@pytest.fixture()
async def session_factory():  # type: ignore[misc]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.orm import sessionmaker

    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session():  # type: ignore[misc]
        async with sf() as s:
            yield s

    app.dependency_overrides[dash_get_session] = override_session
    yield sf
    app.dependency_overrides.pop(dash_get_session, None)
    await engine.dispose()


@pytest.fixture()
async def client(session_factory):  # type: ignore[misc]
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    with (
        patch("app.main.init_db"),
        patch("app.main.close_redis"),
        patch("app.main.redis_listener"),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_metrics_includes_ready_for_merge(client) -> None:
    """GET /api/dashboard/metrics response includes ready_for_merge field."""
    with patch("app.routers.dashboard._get_session"):
        resp = await client.get("/api/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "ready_for_merge" in data["column_counts"]


async def test_metrics_includes_in_merge(client) -> None:
    """GET /api/dashboard/metrics response includes in_merge field."""
    with patch("app.routers.dashboard._get_session"):
        resp = await client.get("/api/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "in_merge" in data["column_counts"]


async def test_metrics_excludes_ready_to_merge(client) -> None:
    """GET /api/dashboard/metrics response does not include ready_to_merge."""
    with patch("app.routers.dashboard._get_session"):
        resp = await client.get("/api/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "ready_to_merge" not in data["column_counts"]
