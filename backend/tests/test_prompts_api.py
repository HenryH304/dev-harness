"""Tests for the /api/prompts endpoints."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def app(tmp_path: Path):
    from app.main import app as fastapi_app

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


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def prompt_files(tmp_path: Path):
    """Patch AGENT_TYPES to use temp prompt files."""
    from app.agents import AgentTypeConfig

    files = {}
    for agent_type in ("developer", "reviewer", "tester", "merger"):
        p = tmp_path / f"{agent_type}.md"
        p.write_text(f"# {agent_type.title()} prompt\nDo the thing.")
        files[agent_type] = p

    patched = {
        agent_type: AgentTypeConfig(
            column_binding="to_do",
            timeout=300,
            prompt_path=str(files[agent_type]),
        )
        for agent_type in files
    }

    with mock.patch("app.routers.prompts.AGENT_TYPES", patched):
        yield files


@pytest.mark.asyncio
async def test_list_prompts_returns_all_agents(client, prompt_files):
    resp = await client.get("/api/prompts")
    assert resp.status_code == 200
    data = resp.json()
    agent_types = {p["agent_type"] for p in data}
    # The four kanban agents must be present; directory scanning may add extras (e.g. story-writer)
    assert {"developer", "reviewer", "tester", "merger"}.issubset(agent_types)


@pytest.mark.asyncio
async def test_list_prompts_returns_content(client, prompt_files):
    resp = await client.get("/api/prompts")
    assert resp.status_code == 200
    dev = next(p for p in resp.json() if p["agent_type"] == "developer")
    assert "Developer prompt" in dev["content"]


@pytest.mark.asyncio
async def test_get_prompt_returns_single_agent(client, prompt_files):
    resp = await client.get("/api/prompts/reviewer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_type"] == "reviewer"
    assert "Reviewer prompt" in data["content"]


@pytest.mark.asyncio
async def test_get_prompt_unknown_type_returns_404(client, prompt_files):
    resp = await client.get("/api/prompts/unknown-agent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_prompt_writes_file(client, prompt_files):
    new_content = "# Updated\nNew instructions here."
    resp = await client.put(
        "/api/prompts/developer",
        json={"content": new_content},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == new_content
    assert prompt_files["developer"].read_text() == new_content


@pytest.mark.asyncio
async def test_update_prompt_reflected_in_get(client, prompt_files):
    new_content = "# Merged\nMerge all the things."
    await client.put("/api/prompts/merger", json={"content": new_content})

    resp = await client.get("/api/prompts/merger")
    assert resp.status_code == 200
    assert resp.json()["content"] == new_content


@pytest.mark.asyncio
async def test_update_prompt_unknown_type_returns_404(client, prompt_files):
    resp = await client.put("/api/prompts/ghost", json={"content": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_prompts_empty_file_returns_empty_string(client, tmp_path: Path):
    from app.agents import AgentTypeConfig

    p = tmp_path / "developer.md"
    p.write_text("")
    patched = {
        "developer": AgentTypeConfig(column_binding="to_do", timeout=300, prompt_path=str(p))
    }
    with mock.patch("app.routers.prompts.AGENT_TYPES", patched):
        resp = await client.get("/api/prompts")
    assert resp.status_code == 200
    dev = resp.json()[0]
    assert dev["content"] == ""
