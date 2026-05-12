"""Tests for US-002: Initialize local Dolt remote for the project."""

import os
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "init-beads-remote.sh"


class TestInitScript:
    """scripts/init-beads-remote.sh exists and is executable."""

    def test_script_exists(self) -> None:
        assert SCRIPT.is_file(), "scripts/init-beads-remote.sh not found"

    def test_script_is_executable(self) -> None:
        assert SCRIPT.stat().st_mode & 0o111, "init-beads-remote.sh should be executable"

    def test_script_mentions_beads_remote(self) -> None:
        content = SCRIPT.read_text()
        assert "beads-remote" in content or "BEADS_REMOTE_PATH" in content


class TestEnvExample:
    """.env.example contains BEADS_REMOTE_PATH."""

    def test_env_example_has_beads_remote_path(self) -> None:
        env_example = PROJECT_ROOT / ".env.example"
        assert env_example.is_file(), ".env.example not found"
        content = env_example.read_text()
        assert "BEADS_REMOTE_PATH" in content, ".env.example missing BEADS_REMOTE_PATH"


class TestGitignore:
    """.beads-remote/ is excluded from git."""

    def test_gitignore_has_beads_remote(self) -> None:
        gitignore = PROJECT_ROOT / ".gitignore"
        assert gitignore.is_file(), ".gitignore not found"
        content = gitignore.read_text()
        assert ".beads-remote" in content, ".gitignore missing .beads-remote entry"


class TestScriptCreatesRemote:
    """Running the script creates a valid Dolt remote directory."""

    def test_creates_remote_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            remote_path = Path(tmpdir) / ".beads-remote"
            env = {**os.environ, "BEADS_REMOTE_PATH": f"file://{remote_path}"}
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmpdir,
            )
            assert result.returncode == 0, f"Script failed: {result.stderr}"
            assert remote_path.is_dir(), ".beads-remote not created"

    def test_remote_is_dolt_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            remote_path = Path(tmpdir) / ".beads-remote"
            env = {**os.environ, "BEADS_REMOTE_PATH": f"file://{remote_path}"}
            subprocess.run(
                ["bash", str(SCRIPT)],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmpdir,
            )
            # A Dolt repo has a .dolt directory inside
            assert (remote_path / ".dolt").is_dir(), ".beads-remote is not a dolt repo"

    def test_idempotent_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            remote_path = Path(tmpdir) / ".beads-remote"
            env = {**os.environ, "BEADS_REMOTE_PATH": f"file://{remote_path}"}
            for _ in range(2):
                result = subprocess.run(
                    ["bash", str(SCRIPT)],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=tmpdir,
                )
                assert result.returncode == 0, f"Script failed on run: {result.stderr}"


class TestWorktreeIntegration:
    """bd init + bd dolt remote add + bd dolt push works from a test worktree."""

    def test_bd_push_to_local_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            remote_path = Path(tmpdir) / ".beads-remote"
            worktree_path = Path(tmpdir) / "worktree"
            worktree_path.mkdir()

            # Create the remote using our script
            env = {**os.environ, "BEADS_REMOTE_PATH": f"file://{remote_path}"}
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmpdir,
            )
            assert result.returncode == 0, f"init-beads-remote.sh failed: {result.stderr}"

            # Initialize a git repo in the worktree (bd requires it)
            git_env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            }
            subprocess.run(["git", "init"], cwd=worktree_path, capture_output=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "init"],
                cwd=worktree_path,
                capture_output=True,
                env=git_env,
            )

            # bd init
            result = subprocess.run(
                ["bd", "init"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                env={**os.environ, "BD_NON_INTERACTIVE": "1"},
            )
            assert result.returncode == 0, f"bd init failed: {result.stderr}\n{result.stdout}"

            # bd dolt remote add origin $BEADS_REMOTE_PATH
            beads_remote = f"file://{remote_path}"
            result = subprocess.run(
                ["bd", "dolt", "remote", "add", "origin", beads_remote],
                capture_output=True,
                text=True,
                cwd=worktree_path,
            )
            assert result.returncode == 0, (
                f"bd dolt remote add failed: {result.stderr}\n{result.stdout}"
            )

            # bd dolt push
            result = subprocess.run(
                ["bd", "dolt", "push"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
            )
            assert result.returncode == 0, f"bd dolt push failed: {result.stderr}\n{result.stdout}"
