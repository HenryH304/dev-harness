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


async def spawn_prd_writer(
    feature_request_id: int,
    project: str,
    description: str,
    output_path: str,
) -> SpawnResult:
    """Run ralph in a temp directory to generate a prd.json from a feature description.

    Creates a working directory at /tmp/prd-writer-{id}/, writes an input prd.json
    with the feature description and outputPath, then spawns ralph with the
    story-writer prompt.

    Returns:
        SpawnResult with ticket_id=feature_request_id.
    """
    import tempfile

    story_writer_path = Path(__file__).parent.parent / "prompts" / "story-writer.md"
    prompt = load_prompt(str(story_writer_path))

    work_dir = Path(tempfile.mkdtemp(prefix=f"prd-writer-{feature_request_id}-"))

    input_prd = {
        "project": project,
        "agentType": "prd-writer",
        "featureDescription": description,
        "outputPath": output_path,
        "userStories": [
            {
                "id": "PW-001",
                "title": "Generate PRD from feature description",
                "description": description,
                "acceptanceCriteria": [
                    f"Write a valid prd.json to {output_path}",
                    "All stories are completable in one Ralph iteration",
                    "Dependencies are specified between stories that require them",
                ],
                "priority": 1,
                "passes": False,
            }
        ],
    }

    (work_dir / "prd.json").write_text(json.dumps(input_prd, indent=2))
    (work_dir / "prompt.md").write_text(prompt)
    (work_dir / "progress.txt").write_text("")
    (work_dir / "ralph.log").write_text("")

    timeout_seconds = "600"

    process = await asyncio.create_subprocess_exec(
        "ralph",
        "-timeout",
        timeout_seconds,
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    exit_code = await process.wait()

    return SpawnResult(
        ticket_id=feature_request_id,
        success=exit_code == 0,
        exit_code=exit_code,
    )


async def spawn_spec_writer(
    spec_id: int,
    project: str,
    description: str,
    spec_path: str,
    api_base_url: str,
    amendment_request: str | None = None,
    existing_spec: str | None = None,
) -> SpawnResult:
    """Run ralph in a temp directory to generate a specification document.

    The spec-writer agent reads task context from task.json, then calls the
    dev-harness API to fetch current incomplete stories for the project.
    """
    import tempfile

    spec_writer_path = Path(__file__).parent.parent / "prompts" / "spec-writer.md"
    prompt = load_prompt(str(spec_writer_path))

    work_dir = Path(tempfile.mkdtemp(prefix=f"spec-writer-{spec_id}-"))

    input_prd: dict[str, Any] = {
        "project": project,
        "agentType": "spec-writer",
        "featureDescription": description,
        "specPath": spec_path,
        "apiBaseUrl": api_base_url,
    }
    if amendment_request:
        input_prd["amendmentRequest"] = amendment_request
    if existing_spec:
        input_prd["existingSpec"] = existing_spec

    (work_dir / "prd.json").write_text(json.dumps(input_prd, indent=2))
    (work_dir / "prompt.md").write_text(prompt)
    (work_dir / "progress.txt").write_text("")
    (work_dir / "ralph.log").write_text("")

    process = await asyncio.create_subprocess_exec(
        "ralph",
        "-timeout",
        "600",
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    exit_code = await process.wait()

    return SpawnResult(
        ticket_id=spec_id,
        success=exit_code == 0,
        exit_code=exit_code,
    )


async def spawn_story_converter(
    spec_id: int,
    project: str,
    spec_content: str,
    prd_output_path: str,
) -> SpawnResult:
    """Run the story-writer agent to convert a spec document into prd.json stories.

    Passes the spec content as featureDescription so the story-writer can break
    it into independently-completable user stories.
    """
    import tempfile

    story_writer_path = Path(__file__).parent.parent / "prompts" / "story-writer.md"
    prompt = load_prompt(str(story_writer_path))

    work_dir = Path(tempfile.mkdtemp(prefix=f"story-converter-{spec_id}-"))

    input_prd = {
        "project": project,
        "agentType": "story-writer",
        "featureDescription": spec_content,
        "outputPath": prd_output_path,
        "userStories": [
            {
                "id": "SC-001",
                "title": "Convert specification to user stories",
                "description": "Convert the provided specification into user stories",
                "acceptanceCriteria": [
                    f"Write a valid prd.json to {prd_output_path}",
                    "All stories are completable in one Ralph iteration",
                    "Dependencies are correctly specified",
                ],
                "priority": 1,
                "passes": False,
            }
        ],
    }

    (work_dir / "prd.json").write_text(json.dumps(input_prd, indent=2))
    (work_dir / "prompt.md").write_text(prompt)
    (work_dir / "progress.txt").write_text("")
    (work_dir / "ralph.log").write_text("")

    process = await asyncio.create_subprocess_exec(
        "ralph",
        "-timeout",
        "600",
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    exit_code = await process.wait()

    return SpawnResult(
        ticket_id=spec_id,
        success=exit_code == 0,
        exit_code=exit_code,
    )
