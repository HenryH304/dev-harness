"""Ralph loop integration — delegates agent execution to the host via Redis RPC.

The container publishes a spawn request to `ralph:spawn`. The host-side
executor (executor.py) picks it up, runs ralph in the specified directory,
and publishes the result to `ralph:result:{request_id}`. The container waits
for that response and returns a SpawnResult.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents import get_agent_config, load_prompt

# Temp working directories for spec/story writers go here — must be on the
# shared volume so the host executor can access them.
_WORK_BASE = Path.home() / "Projects" / ".devharness-tmp"


@dataclass
class SpawnResult:
    """Result of spawning a ralph agent process."""

    ticket_id: int
    success: bool
    exit_code: int


async def _spawn_via_host(cwd: str, timeout: int) -> int:
    """Send a spawn request to the host executor via Redis and wait for result.

    Returns the ralph exit code. Returns 1 on timeout or communication error.
    """
    from app.redis_client import get_redis

    request_id = uuid.uuid4().hex
    response_channel = f"ralph:result:{request_id}"

    client = await get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(response_channel)

    await client.publish(
        "ralph:spawn",
        json.dumps(
            {
                "request_id": request_id,
                "response_channel": response_channel,
                "cwd": cwd,
                "timeout": timeout,
            }
        ),
    )

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout + 60  # generous buffer over ralph's own timeout
    exit_code = 1
    try:
        while loop.time() < deadline:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.05)
                continue
            data = json.loads(message["data"])
            exit_code = data.get("exit_code", 1)
            break
        else:
            import logging
            logging.getLogger(__name__).warning(
                "ralph spawn timed out waiting for host response: cwd=%s", cwd
            )
    finally:
        await pubsub.unsubscribe(response_channel)

    return exit_code


def _make_work_dir(prefix: str) -> Path:
    """Create a uniquely-named working directory under the shared work base."""
    _WORK_BASE.mkdir(parents=True, exist_ok=True)
    work_dir = _WORK_BASE / f"{prefix}-{uuid.uuid4().hex[:8]}"
    work_dir.mkdir()
    return work_dir


def build_prd_json(
    ticket: dict[str, Any],
    notes: list[dict[str, str]],
    agent_type: str,
) -> dict[str, Any]:
    """Build a prd.json payload for the ralph agent."""
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
    """Spawn a ralph loop process for an agent task in the ticket's worktree."""
    worktree_path = ticket.get("worktree_path")
    if not worktree_path:
        raise ValueError("Ticket has no worktree_path — create a worktree first")

    wt = Path(worktree_path)
    if not wt.exists():
        raise ValueError(f"Worktree path does not exist: {worktree_path}")

    agent_config = get_agent_config(agent_type)
    prompt = load_prompt(agent_config.prompt_path)

    prd_data = build_prd_json(ticket, notes, agent_type)
    (wt / "prd.json").write_text(json.dumps(prd_data, indent=2))
    (wt / "prompt.md").write_text(prompt)
    for filename in ("progress.txt", "ralph.log"):
        fp = wt / filename
        if not fp.exists():
            fp.write_text("")

    timeout = agent_config.timeout
    exit_code = await _spawn_via_host(worktree_path, timeout)

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
    """Run the story-writer agent to generate a prd.json from a feature description."""
    story_writer_path = Path(__file__).parent.parent / "prompts" / "story-writer.md"
    prompt = load_prompt(str(story_writer_path))

    work_dir = _make_work_dir(f"prd-writer-{feature_request_id}")

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

    exit_code = await _spawn_via_host(str(work_dir), 600)

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
    """Run the spec-writer agent to generate a specification document."""
    spec_writer_path = Path(__file__).parent.parent / "prompts" / "spec-writer.md"
    prompt = load_prompt(str(spec_writer_path))

    work_dir = _make_work_dir(f"spec-writer-{spec_id}")

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

    exit_code = await _spawn_via_host(str(work_dir), 600)

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
    """Run the story-writer agent to convert a spec document into prd.json stories."""
    story_writer_path = Path(__file__).parent.parent / "prompts" / "story-writer.md"
    prompt = load_prompt(str(story_writer_path))

    work_dir = _make_work_dir(f"story-converter-{spec_id}")

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

    exit_code = await _spawn_via_host(str(work_dir), 600)

    return SpawnResult(
        ticket_id=spec_id,
        success=exit_code == 0,
        exit_code=exit_code,
    )
