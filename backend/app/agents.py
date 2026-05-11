"""Agent type definitions and prompt loading."""

from dataclasses import dataclass
from pathlib import Path

from app.config import DEFAULT_AGENT_TIMEOUTS

_PROMPTS_DIR = str(Path(__file__).parent.parent / "prompts")


@dataclass(frozen=True)
class AgentTypeConfig:
    """Configuration for an agent type."""

    column_binding: str
    timeout: int
    prompt_path: str


AGENT_TYPES: dict[str, AgentTypeConfig] = {
    "developer": AgentTypeConfig(
        column_binding="to_do",
        timeout=DEFAULT_AGENT_TIMEOUTS["developer"],
        prompt_path=f"{_PROMPTS_DIR}/developer.md",
    ),
    "reviewer": AgentTypeConfig(
        column_binding="ready_for_review",
        timeout=DEFAULT_AGENT_TIMEOUTS["reviewer"],
        prompt_path=f"{_PROMPTS_DIR}/reviewer.md",
    ),
    "tester": AgentTypeConfig(
        column_binding="ready_for_test",
        timeout=DEFAULT_AGENT_TIMEOUTS["tester"],
        prompt_path=f"{_PROMPTS_DIR}/tester.md",
    ),
    "merger": AgentTypeConfig(
        column_binding="ready_for_merge",
        timeout=DEFAULT_AGENT_TIMEOUTS["merger"],
        prompt_path=f"{_PROMPTS_DIR}/merger.md",
    ),
}


def get_agent_config(agent_type: str) -> AgentTypeConfig:
    """Get configuration for an agent type.

    Raises ValueError if the agent type is unknown.
    """
    if agent_type not in AGENT_TYPES:
        raise ValueError(f"Unknown agent type: {agent_type}")
    return AGENT_TYPES[agent_type]


def load_prompt(prompt_path: str) -> str:
    """Load a prompt from a file path.

    Returns the file content if it exists, otherwise returns a fallback placeholder.
    """
    path = Path(prompt_path)
    if path.is_file():
        return path.read_text()

    # Extract agent type name from filename for the placeholder
    agent_name = path.stem
    return (
        f"# {agent_name.title()} Agent Placeholder Prompt\n\n"
        f"This is a placeholder prompt for the {agent_name} agent.\n"
        f"Replace this by creating a prompt file at: {prompt_path}\n"
    )
