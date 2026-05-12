"""Tests for US-004: Update merger.md — beads initialization and phase loop."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
MERGER_MD = PROJECT_ROOT / "backend" / "prompts" / "merger.md"
FORMULA_IN_BEADS = PROJECT_ROOT / ".beads" / "formulas" / "merge-molecule.formula.toml"


def _read_merger_md() -> str:
    return MERGER_MD.read_text()


class TestMergerMdBeadsInit:
    """merger.md instructs the agent to initialize beads at the start."""

    def test_bd_init_instruction_present(self) -> None:
        assert "bd init" in _read_merger_md()

    def test_bd_dolt_remote_add_origin_instruction(self) -> None:
        assert "bd dolt remote add origin" in _read_merger_md()

    def test_beads_remote_path_env_var_referenced(self) -> None:
        assert "BEADS_REMOTE_PATH" in _read_merger_md()

    def test_bd_dolt_pull_for_resuming_existing_beads(self) -> None:
        assert "bd dolt pull" in _read_merger_md()

    def test_check_for_beads_dir_existence(self) -> None:
        content = _read_merger_md()
        assert ".beads" in content, ".beads directory reference not found in merger.md"


class TestMergerMdMoleculeSpawn:
    """merger.md instructs agent to spawn merge molecule if no beads exist."""

    def test_bd_list_json_check_present(self) -> None:
        assert "bd list --json" in _read_merger_md()

    def test_bd_mol_pour_instruction_present(self) -> None:
        assert "bd mol pour" in _read_merger_md()

    def test_skip_spawn_if_beads_already_exist(self) -> None:
        """Instructions must say to skip spawning if beads already exist."""
        content = _read_merger_md()
        # Must mention skipping or conditionally spawning the molecule
        has_conditional = (
            "no beads" in content.lower()
            or "if bd list" in content.lower()
            or "already exist" in content.lower()
            or "skip" in content.lower()
        )
        assert has_conditional, (
            "merger.md must instruct agent to skip molecule creation if beads already exist"
        )


class TestMergerMdPhaseLoop:
    """merger.md instructs agent to use bd ready for the phase loop."""

    def test_bd_ready_json_limit_instruction(self) -> None:
        content = _read_merger_md()
        assert "bd ready" in content, "bd ready command not found in merger.md"

    def test_bd_close_instruction_present(self) -> None:
        assert "bd close" in _read_merger_md()

    def test_bd_dolt_push_after_each_phase(self) -> None:
        assert "bd dolt push" in _read_merger_md()

    def test_complete_signal_only_after_cleanup_bead(self) -> None:
        """<promise>COMPLETE</promise> must appear after the cleanup phase section."""
        content = _read_merger_md()
        cleanup_pos = content.find("cleanup")
        complete_pos = content.find("<promise>COMPLETE</promise>")
        assert cleanup_pos != -1, "cleanup bead not mentioned in merger.md"
        assert complete_pos != -1, "<promise>COMPLETE</promise> not found in merger.md"
        assert complete_pos > cleanup_pos, (
            "<promise>COMPLETE</promise> must appear after the cleanup bead section"
        )

    def test_five_phases_documented(self) -> None:
        content = _read_merger_md()
        phases = ["fetch-main", "rebase", "run-tests", "merge-push", "cleanup"]
        missing = [p for p in phases if p not in content]
        assert not missing, f"Phase(s) not mentioned in merger.md: {missing}"


class TestBeadsWorkflowResumability:
    """Integration: bd ready reflects closed beads, enabling resume."""

    def _setup_beads_env(self, tmpdir: Path) -> None:
        """Initialize git repo + bd workspace + pour merge-molecule."""
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        }
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
            env=git_env,
            check=True,
        )
        bd_env = {**os.environ, "BD_NON_INTERACTIVE": "1"}
        result = subprocess.run(
            ["bd", "init"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
            env=bd_env,
        )
        assert result.returncode == 0, f"bd init failed: {result.stderr}\n{result.stdout}"

        formulas_dir = tmpdir / ".beads" / "formulas"
        formulas_dir.mkdir(parents=True, exist_ok=True)
        dest = formulas_dir / FORMULA_IN_BEADS.name
        dest.write_text(FORMULA_IN_BEADS.read_text())

        pour = subprocess.run(
            ["bd", "mol", "pour", "merge-molecule", "--var", "ticket_id=TEST-42"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert pour.returncode == 0, f"bd mol pour failed: {pour.stderr}\n{pour.stdout}"

    def _bd_ready_first(self, tmpdir: Path) -> dict:
        """Return the first ready bead as a dict."""
        result = subprocess.run(
            ["bd", "ready", "--json", "--limit", "1"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0, f"bd ready failed: {result.stderr}"
        issues = json.loads(result.stdout)
        assert len(issues) > 0, "bd ready returned no issues"
        return issues[0]

    def test_fresh_pour_ready_returns_fetch_main(self) -> None:
        """After pouring, bd ready returns the fetch-main bead first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            self._setup_beads_env(tmpdir)
            bead = self._bd_ready_first(tmpdir)
            assert "Fetch" in bead.get("title", "") or "fetch" in bead.get("title", ""), (
                f"Expected fetch-main bead first, got: {bead.get('title')!r}"
            )

    def test_after_closing_fetch_main_ready_returns_rebase(self) -> None:
        """Simulated resume: close fetch-main, bd ready returns rebase bead next."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            self._setup_beads_env(tmpdir)

            # Get and close the fetch-main bead
            fetch_bead = self._bd_ready_first(tmpdir)
            fetch_id = fetch_bead["id"]
            close = subprocess.run(
                ["bd", "close", str(fetch_id)],
                capture_output=True,
                text=True,
                cwd=tmpdir,
            )
            assert close.returncode == 0, f"bd close failed: {close.stderr}"

            # Now bd ready should return the rebase bead
            next_bead = self._bd_ready_first(tmpdir)
            assert "Rebase" in next_bead.get("title", "") or "rebase" in next_bead.get("title", ""), (
                f"Expected rebase bead after fetch-main closed, got: {next_bead.get('title')!r}"
            )

    def test_after_closing_all_but_cleanup_ready_returns_cleanup(self) -> None:
        """All phases except cleanup closed → bd ready returns cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            self._setup_beads_env(tmpdir)

            phases_to_close = ["fetch-main", "rebase", "run-tests", "merge-push"]
            for _ in phases_to_close:
                bead = self._bd_ready_first(tmpdir)
                close = subprocess.run(
                    ["bd", "close", str(bead["id"])],
                    capture_output=True,
                    text=True,
                    cwd=tmpdir,
                )
                assert close.returncode == 0, (
                    f"bd close {bead['id']} failed: {close.stderr}\n"
                    f"bead title: {bead.get('title')}"
                )

            cleanup_bead = self._bd_ready_first(tmpdir)
            assert "Clean" in cleanup_bead.get("title", "") or "cleanup" in cleanup_bead.get("title", ""), (
                f"Expected cleanup bead last, got: {cleanup_bead.get('title')!r}"
            )
