"""Tests for US-006: Replace merge-failures.json with beads state in the backend."""

import json
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).parent.parent.parent
MERGER_MD = PROJECT_ROOT / "backend" / "prompts" / "merger.md"


def _read_merger_md() -> str:
    return MERGER_MD.read_text()


# ---------------------------------------------------------------------------
# merger.md content tests
# ---------------------------------------------------------------------------


class TestMergerMdBlockerMetadata:
    """merger.md instructs agent to use bd update --metadata instead of merge-failures.json."""

    def test_merger_md_no_longer_writes_merge_failures_json(self) -> None:
        """The write instruction for merge-failures.json must be removed."""
        content = _read_merger_md()
        # Should not instruct the agent to WRITE merge-failures.json
        lower = content.lower()
        assert "write `merge-failures.json`" not in lower, (
            "merger.md must not instruct the agent to write merge-failures.json"
        )
        assert "write merge-failures.json" not in lower, (
            "merger.md must not instruct the agent to write merge-failures.json"
        )

    def test_merger_md_uses_bd_update_for_blockers(self) -> None:
        """merger.md must instruct the agent to use bd update for genuine blockers."""
        content = _read_merger_md()
        assert "bd update" in content, (
            "merger.md must include 'bd update' for recording genuine blockers"
        )

    def test_merger_md_uses_metadata_flag(self) -> None:
        """merger.md must use --metadata flag in bd update command."""
        content = _read_merger_md()
        assert "--metadata" in content, (
            "merger.md must include '--metadata' flag for bd update blocker recording"
        )

    def test_merger_md_includes_blocker_true_in_metadata(self) -> None:
        """merger.md must show blocker: true in the metadata example."""
        content = _read_merger_md()
        has_blocker = (
            '"blocker": true' in content
            or '"blocker":true' in content
            or "blocker: true" in content
        )
        assert has_blocker, (
            "merger.md must include 'blocker: true' in the bd update --metadata example"
        )

    def test_complete_signal_still_present(self) -> None:
        """COMPLETE signal must still be present in merger.md."""
        assert "<promise>COMPLETE</promise>" in _read_merger_md()

    def test_category_field_in_metadata_example(self) -> None:
        """merger.md must include 'category' field in the metadata example."""
        content = _read_merger_md()
        assert '"category"' in content, (
            "merger.md must include 'category' field in the bd update --metadata example"
        )

    def test_detail_field_in_metadata_example(self) -> None:
        """merger.md must include 'detail' field in the metadata example."""
        content = _read_merger_md()
        assert '"detail"' in content, (
            "merger.md must include 'detail' field in the bd update --metadata example"
        )


# ---------------------------------------------------------------------------
# _read_beads_state unit tests
# ---------------------------------------------------------------------------


class TestReadBeadsState:
    """Unit tests for _read_beads_state helper in agent_loop."""

    def _import(self):
        from app.agent_loop import _read_beads_state
        return _read_beads_state

    def test_returns_none_when_no_beads_dir(self, tmp_path) -> None:
        """Returns None when .beads/ directory does not exist in the worktree."""
        _read_beads_state = self._import()
        result = _read_beads_state(str(tmp_path))
        assert result is None

    def test_returns_dict_with_beads_key_when_dir_exists(self, tmp_path) -> None:
        """Returns a dict with a 'beads' key when .beads/ exists and bd succeeds."""
        _read_beads_state = self._import()
        (tmp_path / ".beads").mkdir()
        beads_data = [{"id": 1, "title": "fetch-main", "metadata": {}}]
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=json.dumps(beads_data), stderr=""
            )
            result = _read_beads_state(str(tmp_path))
        assert result is not None
        assert "beads" in result
        assert result["beads"] == beads_data

    def test_returns_none_when_bd_exits_nonzero(self, tmp_path) -> None:
        """Returns None when bd list exits with a non-zero return code."""
        _read_beads_state = self._import()
        (tmp_path / ".beads").mkdir()
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="error")
            result = _read_beads_state(str(tmp_path))
        assert result is None

    def test_returns_empty_beads_when_bd_list_empty(self, tmp_path) -> None:
        """Returns {'beads': []} when bd list --json returns an empty array."""
        _read_beads_state = self._import()
        (tmp_path / ".beads").mkdir()
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            result = _read_beads_state(str(tmp_path))
        assert result == {"beads": []}

    def test_returns_none_on_invalid_json(self, tmp_path) -> None:
        """Returns None when bd outputs invalid JSON."""
        _read_beads_state = self._import()
        (tmp_path / ".beads").mkdir()
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="not-json", stderr="")
            result = _read_beads_state(str(tmp_path))
        assert result is None

    def test_calls_bd_list_json_in_worktree(self, tmp_path) -> None:
        """bd list --json is called with the worktree path as cwd."""
        _read_beads_state = self._import()
        (tmp_path / ".beads").mkdir()
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            _read_beads_state(str(tmp_path))
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "bd" in cmd
        assert "list" in cmd
        assert "--json" in cmd
        assert call_args[1].get("cwd") == str(tmp_path)


# ---------------------------------------------------------------------------
# Merger outcome classification tests — three branches with mocked bd list
# ---------------------------------------------------------------------------


class TestMergerOutcomeBranches:
    """Three merger outcome branches tested using mocked bd list responses."""

    def _import(self):
        from app.agent_loop import _classify_merger_outcome, _read_beads_state
        return _read_beads_state, _classify_merger_outcome

    def test_complete_on_exit_zero_no_open_beads(self, tmp_path) -> None:
        """Exit 0 + bd list returns [] → 'complete' outcome."""
        _read_beads_state, _classify_merger_outcome = self._import()
        (tmp_path / ".beads").mkdir()
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            state = _read_beads_state(str(tmp_path))
        outcome, details = _classify_merger_outcome(0, state)
        assert outcome == "complete", f"Expected 'complete', got {outcome!r}"
        assert details == []

    def test_retry_on_nonzero_exit_open_beads_no_blocker(self, tmp_path) -> None:
        """Exit non-zero + bd list returns open beads with no blocker → 'retry' outcome."""
        _read_beads_state, _classify_merger_outcome = self._import()
        (tmp_path / ".beads").mkdir()
        open_beads = [{"id": 3, "title": "run-tests", "metadata": {}}]
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=json.dumps(open_beads), stderr=""
            )
            state = _read_beads_state(str(tmp_path))
        outcome, details = _classify_merger_outcome(1, state)
        assert outcome == "retry", f"Expected 'retry', got {outcome!r}"
        assert details == []

    def test_fail_on_blocker_bead_regardless_of_exit_code(self, tmp_path) -> None:
        """bd list contains a bead with blocker:true metadata → 'fail' regardless of exit code."""
        _read_beads_state, _classify_merger_outcome = self._import()
        (tmp_path / ".beads").mkdir()
        blocker_beads = [
            {
                "id": 4,
                "title": "merge-push",
                "metadata": {
                    "blocker": True,
                    "category": "push_failure",
                    "detail": "Authentication failed",
                },
            }
        ]
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=json.dumps(blocker_beads), stderr=""
            )
            state = _read_beads_state(str(tmp_path))

        # Blocker beats exit 0
        outcome, details = _classify_merger_outcome(0, state)
        assert outcome == "fail", f"Expected 'fail' on exit 0 with blocker, got {outcome!r}"
        assert len(details) == 1
        assert details[0]["metadata"]["category"] == "push_failure"

        # Blocker beats exit non-zero too
        outcome2, _ = _classify_merger_outcome(1, state)
        assert outcome2 == "fail", f"Expected 'fail' on exit 1 with blocker, got {outcome2!r}"

    def test_retry_when_exit_zero_but_open_beads_no_blocker(self, tmp_path) -> None:
        """Exit 0 + open beads (no blocker) → 'retry' (something is unfinished)."""
        _read_beads_state, _classify_merger_outcome = self._import()
        (tmp_path / ".beads").mkdir()
        open_beads = [{"id": 5, "title": "cleanup", "metadata": {}}]
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=json.dumps(open_beads), stderr=""
            )
            state = _read_beads_state(str(tmp_path))
        outcome, _ = _classify_merger_outcome(0, state)
        assert outcome == "retry"

    def test_no_beads_state_returns_no_beads_outcome(self) -> None:
        """When _read_beads_state returns None (no .beads/ dir), outcome is 'no_beads'."""
        from app.agent_loop import _classify_merger_outcome
        outcome, details = _classify_merger_outcome(0, None)
        assert outcome == "no_beads"
        assert details == []

    def test_no_beads_state_with_nonzero_exit_returns_no_beads(self) -> None:
        """When _read_beads_state returns None and exit is non-zero, outcome is 'no_beads'."""
        from app.agent_loop import _classify_merger_outcome
        outcome, _ = _classify_merger_outcome(1, None)
        assert outcome == "no_beads"


# ---------------------------------------------------------------------------
# agent_loop stale-file cleanup: merger must not clean up merge-failures.json
# ---------------------------------------------------------------------------


class TestMergerStaleFileCleanup:
    """The stale merge-failures.json cleanup block must be removed for the merger."""

    def test_stale_files_dict_has_no_merger_entry(self) -> None:
        """The stale_files dict in agent_loop should not have a 'merger' key."""
        import inspect

        from app.agent_loop import try_pickup_and_run

        source = inspect.getsource(try_pickup_and_run)
        # Check that merge-failures.json is not in the stale_files dict
        assert "merge-failures.json" not in source, (
            "merge-failures.json must be removed from the stale_files cleanup dict"
        )
