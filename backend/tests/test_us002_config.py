"""Tests for US-002: FastAPI backend base with config loading."""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import AppConfig, load_config
from app.main import app

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestConfigDefaults:
    """Test default configuration values."""

    def test_default_port(self) -> None:
        config = AppConfig()
        assert config.port == 9080

    def test_default_max_agents_system(self) -> None:
        config = AppConfig()
        assert config.max_agents_system == 10

    def test_default_max_agents_per_type(self) -> None:
        config = AppConfig()
        expected = {"developer": 3, "reviewer": 2, "tester": 2, "merger": 1}
        assert config.max_agents_per_type == expected

    def test_default_review_rejection_threshold(self) -> None:
        config = AppConfig()
        assert config.review_rejection_threshold == 3

    def test_default_agent_timeouts(self) -> None:
        config = AppConfig()
        assert config.agent_timeouts == {
            "developer": 1200,
            "reviewer": 600,
            "tester": 600,
            "merger": 300,
        }


class TestConfigFromJson:
    """Test loading config from config.json."""

    def test_load_from_config_json(self, tmp_path: Path) -> None:
        config_data: dict[str, Any] = {
            "port": 3000,
            "max_agents_system": 5,
            "agent_timeouts": {
                "developer": 900,
                "reviewer": 300,
                "tester": 300,
                "merger": 120,
            },
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(config_path=config_file)
        assert config.port == 3000
        assert config.max_agents_system == 5
        assert config.agent_timeouts["developer"] == 900

    def test_missing_config_json_uses_defaults(self, tmp_path: Path) -> None:
        config = load_config(config_path=tmp_path / "nonexistent.json")
        assert config.port == 9080
        assert config.max_agents_system == 10

    def test_partial_config_json_merges_with_defaults(self, tmp_path: Path) -> None:
        config_data: dict[str, Any] = {"port": 4000}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(config_path=config_file)
        assert config.port == 4000
        # Defaults preserved for unspecified values
        assert config.max_agents_system == 10
        assert config.review_rejection_threshold == 3


class TestConfigEnvOverrides:
    """Test that environment variables override config.json values."""

    def test_port_env_overrides_default(self) -> None:
        with patch.dict(os.environ, {"PORT": "5000"}):
            config = load_config()
        assert config.port == 5000

    def test_port_env_overrides_config_json(self, tmp_path: Path) -> None:
        config_data: dict[str, Any] = {"port": 3000}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        with patch.dict(os.environ, {"PORT": "5000"}):
            config = load_config(config_path=config_file)
        assert config.port == 5000

    def test_max_agents_system_env_override(self) -> None:
        with patch.dict(os.environ, {"MAX_AGENTS_SYSTEM": "20"}):
            config = load_config()
        assert config.max_agents_system == 20

    def test_max_agents_per_type_env_override(self) -> None:
        with patch.dict(os.environ, {"MAX_AGENTS_DEVELOPER": "5"}):
            config = load_config()
        assert config.max_agents_per_type["developer"] == 5

    def test_review_rejection_threshold_env_override(self) -> None:
        with patch.dict(os.environ, {"REVIEW_REJECTION_THRESHOLD": "5"}):
            config = load_config()
        assert config.review_rejection_threshold == 5

    def test_agent_timeout_env_overrides(self) -> None:
        with patch.dict(os.environ, {"AGENT_TIMEOUT_DEVELOPER": "1800"}):
            config = load_config()
        assert config.agent_timeouts["developer"] == 1800
        # Others remain default
        assert config.agent_timeouts["reviewer"] == 600


class TestCORSMiddleware:
    """Test that CORS middleware is configured."""

    @pytest.mark.asyncio
    async def test_cors_headers_present(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/api/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


class TestHealthEndpointUS002:
    """Test the health endpoint returns expected format."""

    @pytest.mark.asyncio
    async def test_health_returns_status_ok(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "ok"}
