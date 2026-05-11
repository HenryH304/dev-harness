"""Git worktree management service for DevHarness."""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_RALPH_SETUP_SCRIPT = Path("~/Projects/my-ralph-template/setup.sh").expanduser()


class WorktreeError(Exception):
    """Error during git worktree operations."""


def _run_ralph_setup(worktree_path: str) -> None:
    """Run the Ralph project setup script in the given directory.

    Copies template files (ralph.sh, prompt.md, AGENTS.md) if absent and
    registers runtime files in the git exclude list.  Non-fatal: errors are
    logged so a missing template never blocks worktree creation.
    """
    if not _RALPH_SETUP_SCRIPT.exists():
        return
    try:
        result = subprocess.run(
            [str(_RALPH_SETUP_SCRIPT), worktree_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "Ralph setup script failed for %s: %s",
                worktree_path,
                result.stderr.strip(),
            )
    except subprocess.SubprocessError as exc:
        logger.warning("Ralph setup script error for %s: %s", worktree_path, exc)


def _git_env() -> dict[str, str]:
    """Build git environment with author identity from env vars."""
    import os
    env = os.environ.copy()
    # Ensure committer identity mirrors author if not separately set
    if "GIT_COMMITTER_NAME" not in env and "GIT_AUTHOR_NAME" in env:
        env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"]
    if "GIT_COMMITTER_EMAIL" not in env and "GIT_AUTHOR_EMAIL" in env:
        env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"]
    return env


def _ensure_git_repo(project: Path) -> None:
    """Initialize a git repo with an initial commit on main if one doesn't exist."""
    if (project / ".git").is_dir():
        return

    env = _git_env()
    result = subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        # Older git without -b support
        subprocess.run(["git", "init"], cwd=project, capture_output=True, env=env)
        subprocess.run(
            ["git", "checkout", "-b", "main"],
            cwd=project,
            capture_output=True,
            env=env,
        )

    subprocess.run(
        ["git", "add", "."],
        cwd=project,
        capture_output=True,
        env=env,
    )
    commit = subprocess.run(
        ["git", "commit", "--allow-empty", "-m", f"chore: initialise {project.name}"],
        cwd=project,
        capture_output=True,
        text=True,
        env=env,
    )
    if commit.returncode != 0:
        raise WorktreeError(
            f"Failed to create initial commit in {project}: {commit.stderr.strip()}"
        )
    logger.info("Initialised git repo in %s", project)


def create_worktree(ticket_id: int, project_path: str) -> dict[str, str]:
    """Create a git worktree for a ticket, branched from main.

    Args:
        ticket_id: The ticket ID to create a worktree for.
        project_path: Path to the main git repository.

    Returns:
        Dict with 'worktree_path' and 'branch_name' keys.

    Raises:
        WorktreeError: If the project path doesn't exist or git fails.
    """
    project = Path(project_path)
    if not project.exists():
        raise WorktreeError(f"Project path does not exist: {project_path}")

    _ensure_git_repo(project)

    branch_name = f"ticket/{ticket_id}"
    worktree_dir = project.parent / f"{project.name}-ticket-{ticket_id}"
    worktree_path = str(worktree_dir)

    try:
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, worktree_path, "main"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        if result.returncode != 0:
            raise WorktreeError(
                f"Failed to create worktree: {result.stderr.strip()}"
            )
    except subprocess.SubprocessError as e:
        raise WorktreeError(f"Git error: {e}") from e

    # Add progress.txt and ralph.log to .gitignore in worktree
    gitignore_path = worktree_dir / ".gitignore"
    gitignore_entries = {"progress.txt", "ralph.log"}
    existing_content = ""
    if gitignore_path.exists():
        existing_content = gitignore_path.read_text()
    lines_to_add = [
        entry for entry in gitignore_entries if entry not in existing_content
    ]
    if lines_to_add:
        with open(gitignore_path, "a") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            f.write("\n".join(lines_to_add) + "\n")

    # Copy AGENTS.md from main project if it exists (takes priority over template)
    agents_src = project / "AGENTS.md"
    if agents_src.exists():
        agents_dst = worktree_dir / "AGENTS.md"
        shutil.copy2(str(agents_src), str(agents_dst))

    # Run the Ralph project setup script to copy ralph.sh and other template
    # files, and register runtime files in the git exclude list.
    # This is non-fatal: a missing or failing script is only logged.
    _run_ralph_setup(worktree_path)

    return {
        "worktree_path": worktree_path,
        "branch_name": branch_name,
    }


def delete_worktree(
    ticket_id: int,
    project_path: str,
    worktree_path: str,
) -> None:
    """Delete a git worktree and its branch.

    Args:
        ticket_id: The ticket ID whose worktree to delete.
        project_path: Path to the main git repository.
        worktree_path: Path to the worktree to remove.

    Raises:
        WorktreeError: If git worktree remove fails.
    """
    branch_name = f"ticket/{ticket_id}"

    try:
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WorktreeError(
                f"Failed to remove worktree: {result.stderr.strip()}"
            )
    except subprocess.SubprocessError as e:
        raise WorktreeError(f"Git error: {e}") from e

    # Delete branch (non-fatal if it fails — branch may already be gone)
    try:
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
    except subprocess.SubprocessError:
        pass  # Branch deletion is best-effort
