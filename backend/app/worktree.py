"""Git worktree management service for DevHarness."""

import shutil
import subprocess
from pathlib import Path


class WorktreeError(Exception):
    """Error during git worktree operations."""


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

    branch_name = f"ticket/{ticket_id}"
    worktree_dir = project.parent / f"{project.name}-ticket-{ticket_id}"
    worktree_path = str(worktree_dir)

    try:
        result = subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                branch_name,
                worktree_path,
                "main",
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
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

    # Copy AGENTS.md from main project if it exists
    agents_src = project / "AGENTS.md"
    if agents_src.exists():
        agents_dst = worktree_dir / "AGENTS.md"
        shutil.copy2(str(agents_src), str(agents_dst))

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
