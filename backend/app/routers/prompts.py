"""Agent prompt management API endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents import AGENT_TYPES

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

# Derive the prompts directory from the developer agent path
_PROMPTS_DIR = Path(AGENT_TYPES["developer"].prompt_path).parent


class PromptInfo(BaseModel):
    agent_type: str
    content: str


class UpdatePromptRequest(BaseModel):
    content: str


def _all_prompt_paths() -> dict[str, str]:
    """Return {name: path} for every prompt the system knows about.

    Kanban-driven agents (from AGENT_TYPES) come first; any additional .md
    files in the prompts directory are included automatically.
    """
    configs: dict[str, str] = {at: cfg.prompt_path for at, cfg in AGENT_TYPES.items()}
    if _PROMPTS_DIR.exists():
        for f in sorted(_PROMPTS_DIR.glob("*.md")):
            if f.stem not in configs:
                configs[f.stem] = str(f)
    return configs


def _read_prompt(prompt_path: str) -> str:
    path = Path(prompt_path)
    return path.read_text() if path.is_file() else ""


@router.get("", response_model=list[PromptInfo])
async def list_prompts() -> list[PromptInfo]:
    """Return current prompt content for all agent types including prd-writer."""
    return [
        PromptInfo(agent_type=name, content=_read_prompt(path))
        for name, path in _all_prompt_paths().items()
    ]


@router.get("/{agent_type}", response_model=PromptInfo)
async def get_prompt(agent_type: str) -> PromptInfo:
    """Return the current prompt for a single agent type."""
    paths = _all_prompt_paths()
    if agent_type not in paths:
        raise HTTPException(status_code=404, detail=f"Unknown agent type: {agent_type}")
    return PromptInfo(agent_type=agent_type, content=_read_prompt(paths[agent_type]))


@router.put("/{agent_type}", response_model=PromptInfo)
async def update_prompt(agent_type: str, req: UpdatePromptRequest) -> PromptInfo:
    """Overwrite the prompt file for an agent type.

    Takes effect on the next agent spawn — running agents are not affected.
    """
    paths = _all_prompt_paths()
    if agent_type not in paths:
        raise HTTPException(status_code=404, detail=f"Unknown agent type: {agent_type}")
    path = Path(paths[agent_type])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(req.content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write prompt: {exc}")
    return PromptInfo(agent_type=agent_type, content=req.content)
