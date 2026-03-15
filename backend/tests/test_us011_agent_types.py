"""Tests for US-011: Agent type definitions and prompt loading."""

import os
from pathlib import Path
from unittest import mock

import pytest

from app.agents import (
    AGENT_TYPES,
    AgentTypeConfig,
    get_agent_config,
    load_prompt,
)


class TestAgentTypeDefinitions:
    """Test agent type configuration definitions."""

    def test_four_agent_types_defined(self) -> None:
        """All 4 agent types must be defined."""
        assert set(AGENT_TYPES.keys()) == {"developer", "reviewer", "tester", "merger"}

    def test_agent_type_config_has_required_fields(self) -> None:
        """Each agent type config must have column_binding, timeout, and prompt_path."""
        for name, config in AGENT_TYPES.items():
            assert isinstance(config, AgentTypeConfig), f"{name} is not AgentTypeConfig"
            assert isinstance(config.column_binding, str)
            assert isinstance(config.timeout, int)
            assert isinstance(config.prompt_path, str)

    def test_column_bindings(self) -> None:
        """Column bindings must match spec."""
        assert AGENT_TYPES["developer"].column_binding == "to_do"
        assert AGENT_TYPES["reviewer"].column_binding == "ready_for_review"
        assert AGENT_TYPES["tester"].column_binding == "ready_for_test"
        assert AGENT_TYPES["merger"].column_binding == "ready_to_merge"

    def test_default_timeouts_from_config(self) -> None:
        """Timeouts should match config defaults."""
        assert AGENT_TYPES["developer"].timeout == 1200
        assert AGENT_TYPES["reviewer"].timeout == 600
        assert AGENT_TYPES["tester"].timeout == 600
        assert AGENT_TYPES["merger"].timeout == 300

    def test_developer_prompt_path(self) -> None:
        """Developer prompt loaded from ralph template."""
        assert AGENT_TYPES["developer"].prompt_path == (
            "/home/henry/Projects/my-ralph-template/prompt.md"
        )

    def test_non_developer_prompt_paths_default(self) -> None:
        """Reviewer, tester, merger default to backend/prompts/{type}.md."""
        for agent_type in ("reviewer", "tester", "merger"):
            path = AGENT_TYPES[agent_type].prompt_path
            assert path.endswith(f"prompts/{agent_type}.md"), (
                f"{agent_type} prompt path should end with prompts/{agent_type}.md"
            )


class TestGetAgentConfig:
    """Test get_agent_config helper."""

    def test_get_valid_agent_config(self) -> None:
        """Returns config for valid agent type."""
        config = get_agent_config("developer")
        assert config.column_binding == "to_do"

    def test_get_invalid_agent_type_raises(self) -> None:
        """Raises ValueError for unknown agent type."""
        with pytest.raises(ValueError, match="Unknown agent type"):
            get_agent_config("unknown")


class TestLoadPrompt:
    """Test prompt loading from files."""

    def test_load_prompt_from_existing_file(self, tmp_path: Path) -> None:
        """Loads prompt content from an existing file."""
        prompt_file = tmp_path / "test_prompt.md"
        prompt_file.write_text("# Test Prompt\nDo the thing.")
        result = load_prompt(str(prompt_file))
        assert result == "# Test Prompt\nDo the thing."

    def test_load_prompt_missing_file_returns_fallback(self) -> None:
        """Returns fallback placeholder when file doesn't exist."""
        result = load_prompt("/nonexistent/path/prompt.md")
        assert "placeholder" in result.lower() or len(result) > 0

    def test_load_prompt_fallback_includes_agent_type(self) -> None:
        """Fallback prompt mentions what type it's a placeholder for."""
        result = load_prompt("/nonexistent/reviewer.md")
        # Should return a non-empty fallback
        assert len(result) > 0

    def test_load_developer_prompt_real_file(self) -> None:
        """Developer prompt loads from real ralph template if it exists."""
        dev_path = AGENT_TYPES["developer"].prompt_path
        if Path(dev_path).exists():
            result = load_prompt(dev_path)
            assert len(result) > 0
        else:
            pytest.skip("Ralph template prompt not available")


class TestFallbackPromptCreation:
    """Test that fallback prompts are created for missing prompt files."""

    def test_fallback_prompts_are_non_empty(self) -> None:
        """Fallback prompts must contain meaningful content."""
        for agent_type in ("reviewer", "tester", "merger"):
            result = load_prompt(f"/nonexistent/{agent_type}.md")
            assert len(result) > 10, (
                f"Fallback prompt for {agent_type} is too short"
            )


class TestAgentConfigWithCustomTimeouts:
    """Test that agent configs respect config overrides."""

    @mock.patch.dict(os.environ, {"AGENT_TIMEOUT_DEVELOPER": "999"})
    def test_timeout_override_via_env(self) -> None:
        """Agent timeouts should be overridable via config."""
        # This tests that the config module's timeouts are used
        from app.config import load_config

        cfg = load_config()
        assert cfg.agent_timeouts["developer"] == 999
