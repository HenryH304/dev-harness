"""Agent prompt management API endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents import AGENT_TYPES

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptInfo(BaseModel):
    agent_type: str
    content: str


class UpdatePromptRequest(BaseModel):
    content: str


def _read_prompt(agent_type: str) -> str:
    path = Path(AGENT_TYPES[agent_type].prompt_path)
    if path.is_file():
        return path.read_text()
    return ""


@router.get("", response_model=list[PromptInfo])
async def list_prompts() -> list[PromptInfo]:
    """Return current prompt content for all agent types."""
    return [
        PromptInfo(agent_type=agent_type, content=_read_prompt(agent_type))
        for agent_type in AGENT_TYPES
    ]


@router.get("/{agent_type}", response_model=PromptInfo)
async def get_prompt(agent_type: str) -> PromptInfo:
    """Return the current prompt for a single agent type."""
    if agent_type not in AGENT_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown agent type: {agent_type}")
    return PromptInfo(agent_type=agent_type, content=_read_prompt(agent_type))


@router.put("/{agent_type}", response_model=PromptInfo)
async def update_prompt(agent_type: str, req: UpdatePromptRequest) -> PromptInfo:
    """Overwrite the prompt file for an agent type.

    The new content takes effect on the next agent spawn — running agents
    are not affected.
    """
    if agent_type not in AGENT_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown agent type: {agent_type}")
    path = Path(AGENT_TYPES[agent_type].prompt_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(req.content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write prompt: {exc}")
    return PromptInfo(agent_type=agent_type, content=req.content)
