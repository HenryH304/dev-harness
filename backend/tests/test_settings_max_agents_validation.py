"""Regression tests: max_agents_<type> settings must not accept zero or negative values.

Root cause of incident 2026-05-13: max_agents_merger was set to 0 via the settings
PATCH endpoint, silently disabling merger pickup. Tickets accumulated in ready_for_merge
with no agent ever picking them up.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.main import app
from app.routers.settings import _get_session


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[_get_session] = override
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s
    app.dependency_overrides.pop(_get_session, None)


@pytest.fixture()
async def client(session):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.anyio
class TestMaxAgentsValidation:
    """PATCH /api/settings must reject max_agents_<type> values less than 1."""

    async def test_rejects_zero_for_merger(self, client) -> None:
        """max_agents_merger=0 must be rejected — this disabled merger pickup in prod."""
        resp = await client.patch(
            "/api/settings", json={"settings": {"max_agents_merger": "0"}}
        )
        assert resp.status_code == 422, (
            f"Expected 422 for max_agents_merger=0, got {resp.status_code}: {resp.text}"
        )

    async def test_rejects_zero_for_developer(self, client) -> None:
        """max_agents_developer=0 must be rejected."""
        resp = await client.patch(
            "/api/settings", json={"settings": {"max_agents_developer": "0"}}
        )
        assert resp.status_code == 422

    async def test_rejects_negative_for_any_agent_type(self, client) -> None:
        """Negative max_agents values must be rejected."""
        resp = await client.patch(
            "/api/settings", json={"settings": {"max_agents_tester": "-1"}}
        )
        assert resp.status_code == 422

    async def test_accepts_valid_merger_capacity(self, client) -> None:
        """max_agents_merger=1 must be accepted."""
        resp = await client.patch(
            "/api/settings", json={"settings": {"max_agents_merger": "1"}}
        )
        assert resp.status_code == 200

    async def test_accepts_higher_capacity(self, client) -> None:
        """max_agents_developer=3 must be accepted."""
        resp = await client.patch(
            "/api/settings", json={"settings": {"max_agents_developer": "3"}}
        )
        assert resp.status_code == 200

    async def test_non_max_agents_settings_unaffected(self, client) -> None:
        """Unrelated settings (timeouts etc.) are not restricted by this validation."""
        resp = await client.patch(
            "/api/settings",
            json={"settings": {"agent_timeout_merger": "600", "max_agents_system": "10"}},
        )
        assert resp.status_code == 200
