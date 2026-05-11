"""Tests for US-014: Ralph loop integration for agent execution."""

from typing import Any
from unittest import mock

import pytest

from app.agents import get_agent_config
from app.ralph_runner import (
    SpawnResult,
    build_prd_json,
    spawn_agent,
)


class TestBuildPrdJson:
    """Tests for building the prd.json context file for agents."""

    def test_builds_prd_with_ticket_fields(self) -> None:
        ticket: dict[str, Any] = {
            "id": 1,
            "title": "Implement feature X",
            "description": "Build feature X as described",
            "acceptance_criteria": ["AC1", "AC2"],
            "project": "my-project",
            "priority": 1,
        }
        notes: list[dict[str, str]] = [
            {"author": "dev-abc", "content": "Started work", "note_type": "progress"},
        ]
        result = build_prd_json(ticket, notes, "developer")
        assert result["project"] == "my-project"
        assert len(result["userStories"]) == 1

        story = result["userStories"][0]
        assert story["id"] == 1
        assert story["title"] == "Implement feature X"
        assert story["description"] == "Build feature X as described"
        assert story["acceptanceCriteria"] == ["AC1", "AC2"]
        assert story["priority"] == 1
        assert story["passes"] is False

    def test_includes_previous_notes(self) -> None:
        ticket: dict[str, Any] = {
            "id": 2,
            "title": "Test",
            "description": "Desc",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
        }
        notes = [
            {"author": "reviewer-abc", "content": "Needs fix", "note_type": "review"},
            {"author": "dev-xyz", "content": "Done", "note_type": "progress"},
        ]
        result = build_prd_json(ticket, notes, "reviewer")
        assert result["previousNotes"] == notes

    def test_includes_agent_type(self) -> None:
        ticket: dict[str, Any] = {
            "id": 3,
            "title": "T",
            "description": "D",
            "acceptance_criteria": [],
            "project": "p",
            "priority": 1,
        }
        result = build_prd_json(ticket, [], "tester")
        assert result["agentType"] == "tester"

    def test_includes_branch_name(self) -> None:
        ticket: dict[str, Any] = {
            "id": 4,
            "title": "T",
            "description": "D",
            "acceptance_criteria": [],
            "project": "p",
            "priority": 1,
        }
        result = build_prd_json(ticket, [], "developer")
        assert result["branchName"] == "ticket/4"


class TestSpawnAgent:
    """Tests for spawning the ralph agent process via host executor."""

    @pytest.mark.asyncio
    async def test_spawn_creates_prd_in_worktree(self, tmp_path: Any) -> None:
        """Verify prd.json and prompt.md are written to the worktree before spawning."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        ticket: dict[str, Any] = {
            "id": 10,
            "title": "Test ticket",
            "description": "Test desc",
            "acceptance_criteria": ["AC1"],
            "project": "proj",
            "priority": 1,
            "worktree_path": str(worktree),
        }

        with (
            mock.patch("app.ralph_runner._spawn_via_host", return_value=0) as mock_spawn,
            mock.patch("app.ralph_runner.load_prompt", return_value="# Test prompt"),
        ):
            result = await spawn_agent(ticket, "developer", [])

        assert result.success is True
        assert (worktree / "prd.json").exists()
        assert (worktree / "prompt.md").exists()
        mock_spawn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spawn_runs_ralph_with_timeout(self, tmp_path: Any) -> None:
        """The developer agent timeout (1200s) should be forwarded to _spawn_via_host."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        ticket: dict[str, Any] = {
            "id": 11,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": str(worktree),
        }

        with (
            mock.patch("app.ralph_runner._spawn_via_host", return_value=0) as mock_spawn,
            mock.patch("app.ralph_runner.load_prompt", return_value="# Prompt"),
        ):
            await spawn_agent(ticket, "developer", [])

        _cwd, timeout = mock_spawn.call_args[0]
        assert timeout == 1200  # developer timeout

    @pytest.mark.asyncio
    async def test_spawn_success_returns_success_result(self, tmp_path: Any) -> None:
        """On exit code 0 from host, result should indicate success."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        ticket: dict[str, Any] = {
            "id": 12,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": str(worktree),
        }

        with (
            mock.patch("app.ralph_runner._spawn_via_host", return_value=0),
            mock.patch("app.ralph_runner.load_prompt", return_value="# Prompt"),
        ):
            result = await spawn_agent(ticket, "developer", [])

        assert isinstance(result, SpawnResult)
        assert result.success is True
        assert result.exit_code == 0
        assert result.ticket_id == 12

    @pytest.mark.asyncio
    async def test_spawn_failure_returns_failure_result(self, tmp_path: Any) -> None:
        """On non-zero exit code from host, result should indicate failure."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        ticket: dict[str, Any] = {
            "id": 13,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": str(worktree),
        }

        with (
            mock.patch("app.ralph_runner._spawn_via_host", return_value=1),
            mock.patch("app.ralph_runner.load_prompt", return_value="# Prompt"),
        ):
            result = await spawn_agent(ticket, "developer", [])

        assert result.success is False
        assert result.exit_code == 1
        assert result.ticket_id == 13

    @pytest.mark.asyncio
    async def test_spawn_uses_correct_cwd(self, tmp_path: Any) -> None:
        """The worktree path should be forwarded as cwd to _spawn_via_host."""
        worktree = tmp_path / "my-worktree"
        worktree.mkdir()
        ticket: dict[str, Any] = {
            "id": 14,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": str(worktree),
        }

        with (
            mock.patch("app.ralph_runner._spawn_via_host", return_value=0) as mock_spawn,
            mock.patch("app.ralph_runner.load_prompt", return_value="# Prompt"),
        ):
            await spawn_agent(ticket, "developer", [])

        cwd, _timeout = mock_spawn.call_args[0]
        assert cwd == str(worktree)

    @pytest.mark.asyncio
    async def test_spawn_raises_on_missing_worktree(self) -> None:
        """Should raise ValueError if worktree_path doesn't exist."""
        ticket: dict[str, Any] = {
            "id": 15,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": "/tmp/nonexistent-worktree-devharness",
        }

        with pytest.raises(ValueError, match="Worktree path does not exist"):
            await spawn_agent(ticket, "developer", [])

    @pytest.mark.asyncio
    async def test_spawn_raises_on_missing_worktree_path(self) -> None:
        """Should raise ValueError if ticket has no worktree_path."""
        ticket: dict[str, Any] = {
            "id": 16,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": None,
        }

        with pytest.raises(ValueError, match="no worktree_path"):
            await spawn_agent(ticket, "developer", [])

    @pytest.mark.asyncio
    async def test_spawn_writes_progress_and_log_files(self, tmp_path: Any) -> None:
        """progress.txt and ralph.log should be created in the worktree."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        ticket: dict[str, Any] = {
            "id": 17,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": str(worktree),
        }

        with (
            mock.patch("app.ralph_runner._spawn_via_host", return_value=0),
            mock.patch("app.ralph_runner.load_prompt", return_value="# Prompt"),
        ):
            await spawn_agent(ticket, "developer", [])

        assert (worktree / "prd.json").exists()
        assert (worktree / "progress.txt").exists()
        assert (worktree / "ralph.log").exists()

    @pytest.mark.asyncio
    async def test_spawn_loads_correct_prompt_for_agent_type(self, tmp_path: Any) -> None:
        """Each agent type should use its configured prompt."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        ticket: dict[str, Any] = {
            "id": 18,
            "title": "Test",
            "description": "D",
            "acceptance_criteria": [],
            "project": "proj",
            "priority": 1,
            "worktree_path": str(worktree),
        }

        reviewer_config = get_agent_config("reviewer")
        with (
            mock.patch("app.ralph_runner._spawn_via_host", return_value=0),
            mock.patch(
                "app.ralph_runner.load_prompt", return_value="# Reviewer prompt"
            ) as mock_load,
            mock.patch("app.ralph_runner.get_agent_config", return_value=reviewer_config),
        ):
            await spawn_agent(ticket, "reviewer", [])

        mock_load.assert_called_once_with(reviewer_config.prompt_path)
