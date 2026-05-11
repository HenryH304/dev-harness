"""Tests for US-002: Backend state machine merger pickup → in_merge, complete → done."""

from app.agent_loop import STATE_TO_AGENT
from app.agents import AGENT_TYPES
from app.routers.agents import COMPLETE_NEXT_STATE, PICKUP_NEXT_STATE


def test_merger_column_binding_is_ready_for_merge() -> None:
    """AGENT_TYPES['merger'].column_binding == 'ready_for_merge'."""
    assert AGENT_TYPES["merger"].column_binding == "ready_for_merge"


def test_ready_to_merge_not_in_agent_types_column_bindings() -> None:
    """No agent type uses 'ready_to_merge' as its column_binding."""
    bindings = [cfg.column_binding for cfg in AGENT_TYPES.values()]
    assert "ready_to_merge" not in bindings


def test_state_to_agent_has_ready_for_merge() -> None:
    """STATE_TO_AGENT maps 'ready_for_merge' to 'merger'."""
    assert STATE_TO_AGENT.get("ready_for_merge") == "merger"


def test_state_to_agent_no_ready_to_merge() -> None:
    """STATE_TO_AGENT does not have 'ready_to_merge' key."""
    assert "ready_to_merge" not in STATE_TO_AGENT


def test_pickup_next_state_merger_is_in_merge() -> None:
    """PICKUP_NEXT_STATE['merger'] == 'in_merge'."""
    assert PICKUP_NEXT_STATE["merger"] == "in_merge"


def test_complete_next_state_in_merge_is_done() -> None:
    """COMPLETE_NEXT_STATE['in_merge'] == 'done'."""
    assert COMPLETE_NEXT_STATE.get("in_merge") == "done"


def test_complete_next_state_no_ready_to_merge() -> None:
    """COMPLETE_NEXT_STATE does not contain 'ready_to_merge' key."""
    assert "ready_to_merge" not in COMPLETE_NEXT_STATE
