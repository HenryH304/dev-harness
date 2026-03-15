"""Ralph loop integration for spawning agent processes in worktrees."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents import get_agent_config, load_prompt


@dataclass
class SpawnResult:
    """Result of spawning a ralph agent process."""

    ticket_id: int
    success: bool
    exit_code: int


def build_prd_json(
    ticket: dict[str, Any],
    notes: list[dict[str, str]],
    agent_type: str,
) -> dict[str, Any]:
    """Build a prd.json payload for the ralph agent.

    Contains ticket context: title, description, acceptance criteria,
    previous notes, agent type, and branch name.
    """
    return {
        "project": ticket["project"],
        "branchName": f"ticket/{ticket['id']}",
        "agentType": agent_type,
        "previousNotes": notes,
        "userStories": [
            {
                "id": ticket["id"],
                "title": ticket["title"],
                "description": ticket["description"],
                "acceptanceCriteria": ticket["acceptance_criteria"],
                "priority": ticket["priority"],
                "passes": False,
            }
        ],
    }


async def spawn_agent(
    ticket: dict[str, Any],
    agent_type: str,
    notes: list[dict[str, str]],
) -> SpawnResult:
    """Spawn a ralph loop process for an agent task in the ticket's worktree.

    Args:
        ticket: Ticket data dict (must include worktree_path).
        agent_type: The type of agent (developer, reviewer, tester, merger).
        notes: Previous notes on the ticket for context.

    Returns:
        SpawnResult indicating success/failure and exit code.

    Raises:
        ValueError: If ticket has no worktree_path or path doesn't exist.
    """
    worktree_path = ticket.get("worktree_path")
    if not worktree_path:
        raise ValueError("Ticket has no worktree_path — create a worktree first")

    wt = Path(worktree_path)
    if not wt.exists():
        raise ValueError(f"Worktree path does not exist: {worktree_path}")

    agent_config = get_agent_config(agent_type)
    prompt = load_prompt(agent_config.prompt_path)

    # Build and write prd.json in the worktree
    prd_data = build_prd_json(ticket, notes, agent_type)
    prd_path = wt / "prd.json"
    with open(str(prd_path), "w") as f:
        json.dump(prd_data, f, indent=2)

    # Write prompt to worktree so ralph can find it
    prompt_path = wt / "prompt.md"
    with open(str(prompt_path), "w") as f:
        f.write(prompt)

    # Create progress.txt and ralph.log in worktree (not committed — in .gitignore)
    for filename in ("progress.txt", "ralph.log"):
        filepath = wt / filename
        if not Path(str(filepath)).exists():
            with open(str(filepath), "w") as f:
                f.write("")

    # Spawn ralph process with timeout
    timeout_seconds = str(agent_config.timeout)
    process = await asyncio.create_subprocess_exec(
        "ralph",
        "-timeout",
        timeout_seconds,
        cwd=worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    exit_code = await process.wait()

    return SpawnResult(
        ticket_id=ticket["id"],
        success=exit_code == 0,
        exit_code=exit_code,
    )
