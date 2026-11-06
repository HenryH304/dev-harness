"""Configuration loading from config.json with environment variable overrides."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_AGENT_TIMEOUTS: dict[str, int] = {
    "developer": 1200,  # 20 minutes
    "reviewer": 600,  # 10 minutes
    "tester": 600,  # 10 minutes
    "merger": 300,  # 5 minutes
}

DEFAULT_MAX_AGENTS_PER_TYPE: dict[str, int] = {
    "developer": 3,
    "reviewer": 2,
    "tester": 2,
    "merger": 1,
}


@dataclass
class AppConfig:
    """Application configuration with defaults."""

    port: int = 9080
    max_agents_system: int = 10
    review_rejection_threshold: int = 3
    developer_failure_threshold: int = 3
    tester_rejection_threshold: int = 3
    story_writer_timeout: int = 1800  # 30 minutes
    agent_timeouts: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_AGENT_TIMEOUTS))
    max_agents_per_type: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_MAX_AGENTS_PER_TYPE))


async def fetch_db_overrides() -> dict[str, str]:
    """Fetch all Setting rows from the DB as a plain string dict.

    Returns an empty dict on any error so callers can always safely merge.
    """
    from app.main import engine
    from app.models import Setting
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    try:
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(select(Setting))
            return {row.key: row.value for row in result.scalars().all()}
    except Exception:
        return {}


def load_config(
    config_path: Path | None = None,
    db_overrides: dict[str, str] | None = None,
) -> AppConfig:
    """Load config from config.json (if present), then apply env var overrides,
    then apply DB overrides (highest precedence)."""
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.json"

    config = AppConfig()

    # Load from config.json if it exists
    if config_path.is_file():
        with open(config_path) as f:
            data: dict[str, object] = json.load(f)

        if "port" in data and isinstance(data["port"], int):
            config.port = data["port"]
        if "max_agents_system" in data and isinstance(data["max_agents_system"], int):
            config.max_agents_system = data["max_agents_system"]
        if "review_rejection_threshold" in data and isinstance(
            data["review_rejection_threshold"], int
        ):
            config.review_rejection_threshold = data["review_rejection_threshold"]
        if "developer_failure_threshold" in data and isinstance(
            data["developer_failure_threshold"], int
        ):
            config.developer_failure_threshold = data["developer_failure_threshold"]
        if "tester_rejection_threshold" in data and isinstance(
            data["tester_rejection_threshold"], int
        ):
            config.tester_rejection_threshold = data["tester_rejection_threshold"]
        if "agent_timeouts" in data and isinstance(data["agent_timeouts"], dict):
            for key, val in data["agent_timeouts"].items():
                if isinstance(key, str) and isinstance(val, int):
                    config.agent_timeouts[key] = val

    # Environment variable overrides
    port_env = os.environ.get("PORT")
    if port_env is not None:
        config.port = int(port_env)

    max_agents_env = os.environ.get("MAX_AGENTS_SYSTEM")
    if max_agents_env is not None:
        config.max_agents_system = int(max_agents_env)

    for agent_type in DEFAULT_MAX_AGENTS_PER_TYPE:
        env_key = f"MAX_AGENTS_{agent_type.upper()}"
        per_type_env = os.environ.get(env_key)
        if per_type_env is not None:
            config.max_agents_per_type[agent_type] = int(per_type_env)

    rejection_env = os.environ.get("REVIEW_REJECTION_THRESHOLD")
    if rejection_env is not None:
        config.review_rejection_threshold = int(rejection_env)

    dev_fail_env = os.environ.get("DEVELOPER_FAILURE_THRESHOLD")
    if dev_fail_env is not None:
        config.developer_failure_threshold = int(dev_fail_env)

    tester_reject_env = os.environ.get("TESTER_REJECTION_THRESHOLD")
    if tester_reject_env is not None:
        config.tester_rejection_threshold = int(tester_reject_env)

    story_writer_timeout_env = os.environ.get("STORY_WRITER_TIMEOUT")
    if story_writer_timeout_env is not None:
        config.story_writer_timeout = int(story_writer_timeout_env)

    # Per-agent-type timeout overrides
    for agent_type in DEFAULT_AGENT_TIMEOUTS:
        env_key = f"AGENT_TIMEOUT_{agent_type.upper()}"
        timeout_env = os.environ.get(env_key)
        if timeout_env is not None:
            config.agent_timeouts[agent_type] = int(timeout_env)

    # DB overrides — highest precedence (set via the settings UI)
    if db_overrides:
        for agent_type in DEFAULT_AGENT_TIMEOUTS:
            val = db_overrides.get(f"agent_timeout_{agent_type}")
            if val is not None:
                try:
                    config.agent_timeouts[agent_type] = int(val)
                except (ValueError, TypeError):
                    pass
        for agent_type in DEFAULT_MAX_AGENTS_PER_TYPE:
            val = db_overrides.get(f"max_agents_{agent_type}")
            if val is not None:
                try:
                    config.max_agents_per_type[agent_type] = int(val)
                except (ValueError, TypeError):
                    pass
        for key, attr in (
            ("max_agents_system", "max_agents_system"),
            ("review_rejection_threshold", "review_rejection_threshold"),
            ("developer_failure_threshold", "developer_failure_threshold"),
            ("tester_rejection_threshold", "tester_rejection_threshold"),
            ("story_writer_timeout", "story_writer_timeout"),
        ):
            val = db_overrides.get(key)
            if val is not None:
                try:
                    setattr(config, attr, int(val))
                except (ValueError, TypeError):
                    pass

    return config
