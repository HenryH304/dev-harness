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


@dataclass
class AppConfig:
    """Application configuration with defaults."""

    port: int = 9080
    max_agents_system: int = 10
    max_agents_per_column: int = 10
    review_rejection_threshold: int = 3
    agent_timeouts: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_AGENT_TIMEOUTS))


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from config.json (if present), then apply env var overrides."""
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
        if "max_agents_per_column" in data and isinstance(data["max_agents_per_column"], int):
            config.max_agents_per_column = data["max_agents_per_column"]
        if "review_rejection_threshold" in data and isinstance(
            data["review_rejection_threshold"], int
        ):
            config.review_rejection_threshold = data["review_rejection_threshold"]
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

    max_per_col_env = os.environ.get("MAX_AGENTS_PER_COLUMN")
    if max_per_col_env is not None:
        config.max_agents_per_column = int(max_per_col_env)

    rejection_env = os.environ.get("REVIEW_REJECTION_THRESHOLD")
    if rejection_env is not None:
        config.review_rejection_threshold = int(rejection_env)

    # Per-agent-type timeout overrides
    for agent_type in DEFAULT_AGENT_TIMEOUTS:
        env_key = f"AGENT_TIMEOUT_{agent_type.upper()}"
        timeout_env = os.environ.get(env_key)
        if timeout_env is not None:
            config.agent_timeouts[agent_type] = int(timeout_env)

    return config
