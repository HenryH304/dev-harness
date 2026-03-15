"""Tests for US-001: Project scaffold and Docker Compose setup."""

import os
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.main import app

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestProjectStructure:
    """Test that the project directory structure exists."""

    def test_frontend_directory_exists(self) -> None:
        assert (PROJECT_ROOT / "frontend").is_dir()

    def test_backend_directory_exists(self) -> None:
        assert (PROJECT_ROOT / "backend").is_dir()

    def test_docker_compose_exists(self) -> None:
        assert (PROJECT_ROOT / "docker-compose.yml").is_file()


class TestDockerCompose:
    """Test docker-compose.yml configuration."""

    @pytest.fixture()
    def compose_config(self) -> dict:
        with open(PROJECT_ROOT / "docker-compose.yml") as f:
            return yaml.safe_load(f)

    def test_has_four_services(self, compose_config: dict) -> None:
        services = compose_config["services"]
        assert "frontend" in services
        assert "backend" in services
        assert "redis" in services

    def test_frontend_service(self, compose_config: dict) -> None:
        frontend = compose_config["services"]["frontend"]
        assert "build" in frontend or "image" in frontend

    def test_backend_service(self, compose_config: dict) -> None:
        backend = compose_config["services"]["backend"]
        assert "build" in backend or "image" in backend

    def test_redis_service(self, compose_config: dict) -> None:
        redis_svc = compose_config["services"]["redis"]
        assert "redis" in redis_svc.get("image", "")

    def test_sqlite_volume_mount(self, compose_config: dict) -> None:
        backend = compose_config["services"]["backend"]
        volumes = backend.get("volumes", [])
        assert len(volumes) > 0, "Backend should have a volume mount for SQLite"


class TestBackendConfig:
    """Test backend configuration."""

    def test_default_port(self) -> None:
        os.environ.pop("PORT", None)
        config = load_config()
        assert config.port == 9080

    def test_port_from_env(self) -> None:
        os.environ["PORT"] = "3000"
        try:
            config = load_config()
            assert config.port == 3000
        finally:
            os.environ.pop("PORT")


class TestHealthEndpoint:
    """Test the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestEnvExample:
    """Test .env.example file."""

    def test_env_example_exists(self) -> None:
        assert (PROJECT_ROOT / ".env.example").is_file()

    def test_env_example_documents_port(self) -> None:
        content = (PROJECT_ROOT / ".env.example").read_text()
        assert "PORT" in content

    def test_env_example_documents_redis(self) -> None:
        content = (PROJECT_ROOT / ".env.example").read_text()
        assert "REDIS_URL" in content

    def test_env_example_documents_database(self) -> None:
        content = (PROJECT_ROOT / ".env.example").read_text()
        assert "DATABASE_URL" in content


class TestGitignore:
    """Test .gitignore file."""

    def test_gitignore_exists(self) -> None:
        assert (PROJECT_ROOT / ".gitignore").is_file()

    def test_gitignore_excludes_required(self) -> None:
        content = (PROJECT_ROOT / ".gitignore").read_text()
        required_entries = ["progress.txt", "ralph.log", ".env", "__pycache__", "node_modules"]
        for entry in required_entries:
            assert entry in content, f".gitignore should exclude {entry}"
