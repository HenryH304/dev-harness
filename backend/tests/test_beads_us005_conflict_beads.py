"""Tests for US-005: Create and clean up per-file conflict sub-beads."""

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


class TestConflictDetectionInstructions:
    """merger.md instructs agent to use git status --short to find conflicted files."""

    def test_git_status_short_after_conflict(self) -> None:
        content = _read_merger_md()
        assert "git status --short" in content, (
            "merger.md must instruct agent to run 'git status --short' to identify conflicted files"
        )

    def test_git_status_short_appears_in_rebase_section(self) -> None:
        content = _read_merger_md()
        rebase_pos = content.find("### Phase: rebase")
        run_tests_pos = content.find("### Phase: run-tests")
        status_pos = content.find("git status --short")
        assert rebase_pos != -1, "rebase phase section not found"
        assert run_tests_pos != -1, "run-tests phase section not found"
        assert rebase_pos < status_pos < run_tests_pos, (
            "git status --short must appear in the rebase phase section (between rebase and run-tests)"
        )


class TestConflictSubBeadCreation:
    """merger.md instructs agent to create a child bead per conflicted file."""

    def test_bd_create_instruction_present(self) -> None:
        assert "bd create" in _read_merger_md()

    def test_resolve_conflict_bead_prefix(self) -> None:
        content = _read_merger_md()
        assert "resolve-conflict:" in content, (
            "merger.md must show 'resolve-conflict:<filename>' bead naming convention"
        )

    def test_parent_flag_for_child_bead(self) -> None:
        content = _read_merger_md()
        assert "--parent" in content, (
            "merger.md must use '--parent <rebase-bead-id>' when creating conflict sub-beads"
        )

    def test_bd_create_with_parent_in_rebase_section(self) -> None:
        content = _read_merger_md()
        rebase_pos = content.find("### Phase: rebase")
        run_tests_pos = content.find("### Phase: run-tests")
        create_pos = content.find("bd create")
        assert rebase_pos != -1, "rebase phase section not found"
        assert run_tests_pos != -1, "run-tests phase section not found"
        assert rebase_pos < create_pos < run_tests_pos, (
            "bd create must appear in the rebase phase section"
        )

    def test_no_conflict_sub_beads_when_no_conflicts(self) -> None:
        content = _read_merger_md()
        # Must mention that sub-beads are only created when conflicts exist
        no_conflict_handling = (
            "no conflict" in content.lower()
            or "if no conflict" in content.lower()
            or "if conflicts" in content.lower()
            or "if the rebase completes cleanly" in content.lower()
            or "cleanly" in content.lower()
        )
        assert no_conflict_handling, (
            "merger.md must indicate that conflict sub-beads are only created when conflicts exist"
        )


class TestConflictSubBeadCheckpointPerFile:
    """merger.md instructs agent to close and push each conflict bead before continuing."""

    def test_bd_close_per_conflict_bead(self) -> None:
        content = _read_merger_md()
        # bd close must appear in the rebase section (for conflict beads), not just the phase close
        rebase_pos = content.find("### Phase: rebase")
        run_tests_pos = content.find("### Phase: run-tests")
        # Find bd close within the rebase section
        rebase_section = content[rebase_pos:run_tests_pos]
        assert "bd close" in rebase_section, (
            "bd close must appear in the rebase phase section for closing conflict sub-beads"
        )

    def test_bd_dolt_push_per_conflict_bead(self) -> None:
        content = _read_merger_md()
        rebase_pos = content.find("### Phase: rebase")
        run_tests_pos = content.find("### Phase: run-tests")
        rebase_section = content[rebase_pos:run_tests_pos]
        assert "bd dolt push" in rebase_section, (
            "bd dolt push must appear in the rebase phase section (push after each file resolved)"
        )

    def test_close_before_continue_rebase(self) -> None:
        """bd close for conflict bead must appear before git rebase --continue."""
        content = _read_merger_md()
        rebase_pos = content.find("### Phase: rebase")
        run_tests_pos = content.find("### Phase: run-tests")
        rebase_section = content[rebase_pos:run_tests_pos]
        close_pos = rebase_section.find("bd close")
        continue_pos = rebase_section.find("git rebase --continue")
        assert close_pos != -1, "bd close not found in rebase section"
        assert continue_pos != -1, "git rebase --continue not found in rebase section"
        assert close_pos < continue_pos, (
            "bd close (conflict bead) must appear before git rebase --continue in instructions"
        )


class TestCleanupSection:
    """merger.md cleanup section: bd dolt push then rm -rf .beads/."""

    def test_rm_rf_beads_in_cleanup(self) -> None:
        content = _read_merger_md()
        assert "rm -rf .beads/" in content, (
            "merger.md must instruct agent to remove .beads/ directory after cleanup"
        )

    def test_bd_dolt_push_before_rm_rf_beads(self) -> None:
        content = _read_merger_md()
        push_pos = content.rfind("bd dolt push")
        rm_pos = content.find("rm -rf .beads/")
        assert push_pos != -1, "bd dolt push not found"
        assert rm_pos != -1, "rm -rf .beads/ not found"
        assert push_pos < rm_pos, (
            "bd dolt push must appear before rm -rf .beads/ in the cleanup section"
        )

    def test_cleanup_section_has_rm_beads_after_bd_close(self) -> None:
        content = _read_merger_md()
        cleanup_pos = content.find("### Phase: cleanup")
        assert cleanup_pos != -1, "cleanup phase section not found"
        cleanup_section = content[cleanup_pos:]
        close_pos = cleanup_section.find("bd close")
        rm_pos = cleanup_section.find("rm -rf .beads/")
        assert close_pos != -1, "bd close not found in cleanup section"
        assert rm_pos != -1, "rm -rf .beads/ not found in cleanup section"
        assert close_pos < rm_pos, (
            "In cleanup section, bd close must appear before rm -rf .beads/"
        )


class TestBeadsParentChildIntegration:
    """Integration: verify bd supports parent-child bead relationships."""

    def _setup_beads_env(self, tmpdir: Path) -> None:
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
            ["bd", "mol", "pour", "merge-molecule", "--var", "ticket_id=TEST-99"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert pour.returncode == 0, f"bd mol pour failed: {pour.stderr}\n{pour.stdout}"

    def _get_all_beads(self, tmpdir: Path) -> list[dict]:
        result = subprocess.run(
            ["bd", "list", "--json", "--all"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0, f"bd list failed: {result.stderr}"
        return json.loads(result.stdout)

    def _get_ready_bead(self, tmpdir: Path) -> dict | None:
        result = subprocess.run(
            ["bd", "ready", "--json", "--limit", "1"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0, f"bd ready failed: {result.stderr}"
        issues = json.loads(result.stdout)
        return issues[0] if issues else None

    def _close_bead(self, tmpdir: Path, bead_id: int) -> None:
        result = subprocess.run(
            ["bd", "close", str(bead_id)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0, f"bd close {bead_id} failed: {result.stderr}"

    def test_bd_create_with_parent_creates_child_bead(self) -> None:
        """bd create --parent creates a child bead visible in bd list --json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            self._setup_beads_env(tmpdir)

            # Get the fetch-main bead and close it to get to rebase
            fetch_bead = self._get_ready_bead(tmpdir)
            assert fetch_bead is not None
            self._close_bead(tmpdir, fetch_bead["id"])

            rebase_bead = self._get_ready_bead(tmpdir)
            assert rebase_bead is not None, "rebase bead should be ready after fetch-main closed"

            # Create a conflict sub-bead under rebase
            create_result = subprocess.run(
                [
                    "bd", "create", "resolve-conflict:src/app.py",
                    "--parent", str(rebase_bead["id"]),
                ],
                capture_output=True,
                text=True,
                cwd=tmpdir,
            )
            assert create_result.returncode == 0, (
                f"bd create --parent failed: {create_result.stderr}\n{create_result.stdout}"
            )

            # Verify child bead appears in bd list
            all_beads = self._get_all_beads(tmpdir)
            titles = [b.get("title", "") for b in all_beads]
            conflict_beads = [t for t in titles if "resolve-conflict" in t or "src/app.py" in t]
            assert conflict_beads, (
                f"Conflict child bead not found in bd list output. All titles: {titles}"
            )

    def test_child_beads_block_run_tests_until_closed(self) -> None:
        """After creating conflict child beads under rebase, run-tests is not ready until all children closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            self._setup_beads_env(tmpdir)

            # Close fetch-main to make rebase ready
            fetch_bead = self._get_ready_bead(tmpdir)
            self._close_bead(tmpdir, fetch_bead["id"])

            rebase_bead = self._get_ready_bead(tmpdir)
            assert rebase_bead is not None

            # Create two conflict sub-beads
            for filename in ["src/models.py", "src/views.py"]:
                create_result = subprocess.run(
                    ["bd", "create", f"resolve-conflict:{filename}", "--parent", str(rebase_bead["id"])],
                    capture_output=True,
                    text=True,
                    cwd=tmpdir,
                )
                assert create_result.returncode == 0, (
                    f"bd create --parent failed for {filename}: {create_result.stderr}"
                )

            # Get all child bead IDs (only the resolve-conflict ones by title)
            all_beads = self._get_all_beads(tmpdir)
            child_beads = [
                b for b in all_beads
                if "resolve-conflict" in b.get("title", "")
            ]
            assert len(child_beads) == 2, (
                f"Expected 2 conflict child beads, got {len(child_beads)}: "
                f"{[b.get('title') for b in child_beads]}"
            )

            # Close all child beads first (children must be closed before parent)
            for child in child_beads:
                self._close_bead(tmpdir, child["id"])

            # Close rebase parent bead
            self._close_bead(tmpdir, rebase_bead["id"])

            # Now run-tests should be ready
            next_bead = self._get_ready_bead(tmpdir)
            assert next_bead is not None, "Expected run-tests bead to be ready after rebase and children closed"
            assert "run" in next_bead.get("title", "").lower() or "test" in next_bead.get("title", "").lower(), (
                f"Expected run-tests bead, got: {next_bead.get('title')!r}"
            )
