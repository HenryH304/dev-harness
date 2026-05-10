"""Tests for US-010: Git worktree management service."""

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from app.worktree import WorktreeError, _RALPH_SETUP_SCRIPT, create_worktree, delete_worktree


def _mock_git_side_effect(args: list[str], **kwargs: object) -> mock.MagicMock:
    """Side effect that creates the worktree directory when git worktree add is called."""
    result_obj = mock.MagicMock(returncode=0, stdout="", stderr="")
    if "worktree" in args and "add" in args:
        worktree_dir = args[-2]  # path is second-to-last arg
        os.makedirs(worktree_dir, exist_ok=True)
    return result_obj


class TestCreateWorktree:
    """Tests for create_worktree function."""

    @mock.patch("app.worktree.subprocess.run")
    def test_creates_worktree_with_correct_branch(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Worktree is created with branch named ticket/{ticket_id}."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = _mock_git_side_effect

        create_worktree(ticket_id=42, project_path=project_path)

        # Should call git worktree add with correct branch name
        calls = mock_run.call_args_list
        worktree_call = calls[0]
        args = worktree_call[0][0]
        assert "worktree" in args
        assert "add" in args
        assert "-b" in args
        assert "ticket/42" in args

    @mock.patch("app.worktree.subprocess.run")
    def test_returns_worktree_path_and_branch(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Returns dict with worktree_path and branch_name."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = _mock_git_side_effect

        result = create_worktree(ticket_id=7, project_path=project_path)

        assert result["branch_name"] == "ticket/7"
        assert "worktree_path" in result
        assert "ticket-7" in result["worktree_path"]

    @mock.patch("app.worktree.subprocess.run")
    def test_worktree_path_is_sibling_of_project(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Worktree is created as a sibling directory of the project."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = _mock_git_side_effect

        result = create_worktree(ticket_id=1, project_path=project_path)

        worktree_parent = str(Path(result["worktree_path"]).parent)
        project_parent = str(Path(project_path).parent)
        assert worktree_parent == project_parent

    @mock.patch("app.worktree.subprocess.run")
    def test_branches_from_main(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Worktree is branched from main."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = _mock_git_side_effect

        create_worktree(ticket_id=1, project_path=project_path)

        calls = mock_run.call_args_list
        worktree_call = calls[0]
        args = worktree_call[0][0]
        assert "main" in args

    @mock.patch("app.worktree.subprocess.run")
    def test_adds_gitignore_entries(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """progress.txt and ralph.log added to .gitignore in worktree."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = _mock_git_side_effect

        result = create_worktree(ticket_id=5, project_path=project_path)

        gitignore_path = Path(result["worktree_path"]) / ".gitignore"
        assert gitignore_path.exists()
        content = gitignore_path.read_text()
        assert "progress.txt" in content
        assert "ralph.log" in content

    @mock.patch("app.worktree.subprocess.run")
    def test_copies_agents_md(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """AGENTS.md from main is present in worktree."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        # Create AGENTS.md in project root
        agents_md = Path(project_path) / "AGENTS.md"
        agents_md.write_text("# Agent instructions\nDo things.")
        mock_run.side_effect = _mock_git_side_effect

        result = create_worktree(ticket_id=3, project_path=project_path)

        worktree_agents = Path(result["worktree_path"]) / "AGENTS.md"
        assert worktree_agents.exists()
        assert "Agent instructions" in worktree_agents.read_text()

    def test_raises_on_missing_project_path(self) -> None:
        """Raises WorktreeError if project_path doesn't exist."""
        with pytest.raises(WorktreeError, match="Project path does not exist"):
            create_worktree(ticket_id=1, project_path="/nonexistent/path/to/project")

    @mock.patch("app.worktree.subprocess.run")
    def test_raises_on_git_failure(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Raises WorktreeError if git command fails."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.return_value = mock.MagicMock(
            returncode=128, stdout="", stderr="fatal: not a git repository"
        )

        with pytest.raises(WorktreeError, match="Failed to create worktree"):
            create_worktree(ticket_id=1, project_path=project_path)

    @mock.patch("app.worktree.subprocess.run")
    def test_raises_on_subprocess_exception(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Raises WorktreeError if subprocess raises an exception."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = subprocess.SubprocessError("git not found")

        with pytest.raises(WorktreeError, match="Git error"):
            create_worktree(ticket_id=1, project_path=project_path)

    @mock.patch("app.worktree._RALPH_SETUP_SCRIPT")
    @mock.patch("app.worktree.subprocess.run")
    def test_calls_ralph_setup_script_when_present(
        self, mock_run: mock.MagicMock, mock_script: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Ralph setup script is invoked after worktree creation."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = _mock_git_side_effect
        mock_script.exists.return_value = True
        mock_script.__str__ = lambda _: "/fake/setup.sh"

        create_worktree(ticket_id=99, project_path=project_path)

        setup_calls = [
            c for c in mock_run.call_args_list
            if "/fake/setup.sh" in str(c)
        ]
        assert len(setup_calls) == 1

    @mock.patch("app.worktree._RALPH_SETUP_SCRIPT")
    @mock.patch("app.worktree.subprocess.run")
    def test_ralph_setup_failure_does_not_raise(
        self, mock_run: mock.MagicMock, mock_script: mock.MagicMock, tmp_path: Path
    ) -> None:
        """A non-zero exit from the setup script is logged but does not raise WorktreeError."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_script.exists.return_value = True
        mock_script.__str__ = lambda _: "/fake/setup.sh"

        def side_effect(args: list[str], **kwargs: object) -> mock.MagicMock:
            if "/fake/setup.sh" in str(args):
                return mock.MagicMock(returncode=1, stdout="", stderr="template missing")
            return _mock_git_side_effect(args, **kwargs)

        mock_run.side_effect = side_effect

        # Should not raise despite setup script failure
        result = create_worktree(ticket_id=99, project_path=project_path)
        assert "worktree_path" in result

    @mock.patch("app.worktree._RALPH_SETUP_SCRIPT")
    @mock.patch("app.worktree.subprocess.run")
    def test_ralph_setup_skipped_when_script_absent(
        self, mock_run: mock.MagicMock, mock_script: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Setup script is not invoked when the template is not installed."""
        project_path = str(tmp_path / "myproject")
        os.makedirs(project_path)
        mock_run.side_effect = _mock_git_side_effect
        mock_script.exists.return_value = False
        mock_script.__str__ = lambda _: "/fake/setup.sh"

        create_worktree(ticket_id=99, project_path=project_path)

        setup_calls = [
            c for c in mock_run.call_args_list
            if "/fake/setup.sh" in str(c)
        ]
        assert len(setup_calls) == 0


class TestDeleteWorktree:
    """Tests for delete_worktree function."""

    @mock.patch("app.worktree.subprocess.run")
    def test_removes_worktree(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Calls git worktree remove for the given path."""
        project_path = str(tmp_path / "myproject")
        worktree_path = str(tmp_path / "myproject-ticket-1")
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")

        delete_worktree(
            ticket_id=1,
            project_path=project_path,
            worktree_path=worktree_path,
        )

        calls = mock_run.call_args_list
        # First call: git worktree remove
        remove_args = calls[0][0][0]
        assert "worktree" in remove_args
        assert "remove" in remove_args
        assert worktree_path in remove_args

    @mock.patch("app.worktree.subprocess.run")
    def test_deletes_branch(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Deletes the ticket branch after removing worktree."""
        project_path = str(tmp_path / "myproject")
        worktree_path = str(tmp_path / "myproject-ticket-5")
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")

        delete_worktree(
            ticket_id=5,
            project_path=project_path,
            worktree_path=worktree_path,
        )

        calls = mock_run.call_args_list
        assert len(calls) >= 2
        # Second call: git branch -D
        branch_args = calls[1][0][0]
        assert "branch" in branch_args
        assert "-D" in branch_args
        assert "ticket/5" in branch_args

    @mock.patch("app.worktree.subprocess.run")
    def test_raises_on_git_failure(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Raises WorktreeError if git worktree remove fails."""
        project_path = str(tmp_path / "myproject")
        worktree_path = str(tmp_path / "myproject-ticket-1")
        mock_run.return_value = mock.MagicMock(
            returncode=1, stdout="", stderr="error: worktree not found"
        )

        with pytest.raises(WorktreeError, match="Failed to remove worktree"):
            delete_worktree(
                ticket_id=1,
                project_path=project_path,
                worktree_path=worktree_path,
            )

    @mock.patch("app.worktree.subprocess.run")
    def test_raises_on_subprocess_exception(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Raises WorktreeError if subprocess raises."""
        project_path = str(tmp_path / "myproject")
        worktree_path = str(tmp_path / "myproject-ticket-1")
        mock_run.side_effect = subprocess.SubprocessError("git error")

        with pytest.raises(WorktreeError, match="Git error"):
            delete_worktree(
                ticket_id=1,
                project_path=project_path,
                worktree_path=worktree_path,
            )

    @mock.patch("app.worktree.subprocess.run")
    def test_branch_delete_failure_does_not_raise(
        self, mock_run: mock.MagicMock, tmp_path: Path
    ) -> None:
        """Branch deletion failure is non-fatal (branch may already be gone)."""
        project_path = str(tmp_path / "myproject")
        worktree_path = str(tmp_path / "myproject-ticket-1")

        def side_effect(args: list[str], **kwargs: object) -> mock.MagicMock:
            if "branch" in args:
                return mock.MagicMock(
                    returncode=1, stdout="", stderr="error: branch not found"
                )
            return mock.MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        # Should not raise
        delete_worktree(
            ticket_id=1,
            project_path=project_path,
            worktree_path=worktree_path,
        )
