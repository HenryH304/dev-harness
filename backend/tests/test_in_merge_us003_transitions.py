"""Tests for US-003: Backend allowed transitions for new states."""

from app.routers.transitions import ALLOWED_TRANSITIONS


def test_in_test_allows_ready_for_merge() -> None:
    """in_test → ready_for_merge is allowed."""
    assert "ready_for_merge" in ALLOWED_TRANSITIONS["in_test"]


def test_in_test_does_not_allow_ready_to_merge() -> None:
    """in_test no longer allows ready_to_merge."""
    assert "ready_to_merge" not in ALLOWED_TRANSITIONS["in_test"]


def test_ready_to_merge_key_removed() -> None:
    """ready_to_merge is not a key in ALLOWED_TRANSITIONS."""
    assert "ready_to_merge" not in ALLOWED_TRANSITIONS


def test_ready_for_merge_allows_in_merge_and_blocked() -> None:
    """ready_for_merge → {in_merge, blocked} are valid transitions."""
    allowed = ALLOWED_TRANSITIONS["ready_for_merge"]
    assert "in_merge" in allowed
    assert "blocked" in allowed


def test_in_merge_allows_done_and_blocked() -> None:
    """in_merge → {done, blocked} are valid transitions."""
    allowed = ALLOWED_TRANSITIONS["in_merge"]
    assert "done" in allowed
    assert "blocked" in allowed
