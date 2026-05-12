"""Tests for US-003: Define the merge molecule template."""

import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
FORMULA_IN_BEADS = PROJECT_ROOT / ".beads" / "formulas" / "merge-molecule.formula.toml"
FORMULA_IN_BACKEND = PROJECT_ROOT / "backend" / "beads" / "merge-molecule.formula.toml"

EXPECTED_STEP_IDS = ["fetch-main", "rebase", "run-tests", "merge-push", "cleanup"]
EXPECTED_DEPS = {
    "rebase": ["fetch-main"],
    "run-tests": ["rebase"],
    "merge-push": ["run-tests"],
    "cleanup": ["merge-push"],
}
# Title substrings unique to each step (variable-free parts)
STEP_TITLE_SUBSTRINGS = [
    "Fetch latest main",
    "Rebase",
    "Run tests",
    "Merge and push",
    "Clean up after merging",
]


class TestFormulaFileExists:
    """Formula file exists at the expected paths."""

    def test_formula_in_beads_formulas(self) -> None:
        assert FORMULA_IN_BEADS.is_file(), f"Formula not found at {FORMULA_IN_BEADS}"

    def test_formula_in_backend_beads(self) -> None:
        assert FORMULA_IN_BACKEND.is_file(), f"Formula not found at {FORMULA_IN_BACKEND}"


class TestFormulaTomlStructure:
    """Formula is valid TOML with expected structure."""

    def _load_formula(self) -> dict:
        return tomllib.loads(FORMULA_IN_BEADS.read_text())

    def test_valid_toml(self) -> None:
        data = self._load_formula()
        assert isinstance(data, dict)

    def test_formula_name(self) -> None:
        data = self._load_formula()
        assert data.get("formula") == "merge-molecule"

    def test_has_five_steps(self) -> None:
        data = self._load_formula()
        steps = data.get("steps", [])
        assert len(steps) == 5, f"Expected 5 steps, found {len(steps)}"

    def test_step_ids_match_expected(self) -> None:
        data = self._load_formula()
        step_ids = [s["id"] for s in data.get("steps", [])]
        assert step_ids == EXPECTED_STEP_IDS

    def test_dependency_edges(self) -> None:
        data = self._load_formula()
        step_by_id = {s["id"]: s for s in data.get("steps", [])}
        for step_id, expected_needs in EXPECTED_DEPS.items():
            actual_needs = step_by_id[step_id].get("needs", [])
            assert actual_needs == expected_needs, (
                f"Step '{step_id}' needs {actual_needs!r}, expected {expected_needs!r}"
            )

    def test_fetch_main_has_no_deps(self) -> None:
        data = self._load_formula()
        step_by_id = {s["id"]: s for s in data.get("steps", [])}
        assert "needs" not in step_by_id.get("fetch-main", {})

    def test_execution_agent_type_is_merger(self) -> None:
        data = self._load_formula()
        metadata = data.get("metadata", {})
        agent_type = metadata.get("execution_agent_type") or data.get(
            "execution_agent_type"
        )
        assert agent_type == "merger", (
            f"execution_agent_type must be 'merger', got {agent_type!r}"
        )


class TestFormulaDiscoverability:
    """bd formula list finds merge-molecule from the project directory."""

    def test_formula_list_finds_merge_molecule(self) -> None:
        result = subprocess.run(
            ["bd", "formula", "list"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"bd formula list failed: {result.stderr}"
        assert "merge-molecule" in result.stdout, (
            f"'merge-molecule' not found in bd formula list:\n{result.stdout}"
        )

    def test_formula_cook_dry_run(self) -> None:
        """Cook succeeds when passed the full formula file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            _setup_bd_worktree(tmpdir, FORMULA_IN_BEADS)

            result = subprocess.run(
                ["bd", "cook", str(FORMULA_IN_BEADS), "--dry-run"],
                capture_output=True,
                text=True,
                cwd=tmpdir,
            )
            assert result.returncode == 0, (
                f"bd cook --dry-run failed:\n{result.stderr}\n{result.stdout}"
            )
            output = result.stdout + result.stderr
            assert "5" in output or "merge-molecule" in output, (
                f"Unexpected cook output:\n{output}"
            )


def _setup_bd_worktree(tmpdir: Path, formula_src: Path) -> None:
    """Initialize a git repo + bd workspace with the merge-molecule formula."""
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=tmpdir,
        capture_output=True,
        env=git_env,
    )
    result = subprocess.run(
        ["bd", "init"],
        capture_output=True,
        text=True,
        cwd=tmpdir,
        env={**os.environ, "BD_NON_INTERACTIVE": "1"},
    )
    assert result.returncode == 0, f"bd init failed: {result.stderr}\n{result.stdout}"

    formulas_dir = tmpdir / ".beads" / "formulas"
    formulas_dir.mkdir(parents=True, exist_ok=True)
    dest = formulas_dir / formula_src.name
    dest.write_text(formula_src.read_text())


class TestMoleculeSpawn:
    """Spawning the formula creates 5 phase beads with correct dependency edges."""

    def _pour_and_list(self, tmpdir: Path) -> list[dict]:
        """Pour the merge-molecule and return bd list --json output."""
        result = subprocess.run(
            ["bd", "mol", "pour", "merge-molecule", "--var", "ticket_id=TEST-1"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0, (
            f"bd mol pour failed:\n{result.stderr}\n{result.stdout}"
        )

        list_result = subprocess.run(
            ["bd", "list", "--json", "--all"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert list_result.returncode == 0, (
            f"bd list --json failed: {list_result.stderr}"
        )
        return json.loads(list_result.stdout)

    def test_spawn_produces_five_phase_beads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            _setup_bd_worktree(tmpdir, FORMULA_IN_BEADS)
            issues = self._pour_and_list(tmpdir)

            titles = [i.get("title", "") for i in issues]
            found = [
                substr
                for substr in STEP_TITLE_SUBSTRINGS
                if any(substr in t for t in titles)
            ]
            assert len(found) == 5, (
                f"Expected 5 phase beads, matched {len(found)}: {found}\n"
                f"All titles: {titles}"
            )

    def test_fetch_main_bead_has_no_blocks_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            _setup_bd_worktree(tmpdir, FORMULA_IN_BEADS)
            issues = self._pour_and_list(tmpdir)

            fetch_beads = [i for i in issues if "Fetch latest main" in i.get("title", "")]
            assert len(fetch_beads) >= 1, "fetch-main bead not found"
            blocks = [
                d for d in fetch_beads[0].get("dependencies", [])
                if d["type"] == "blocks"
            ]
            assert len(blocks) == 0, (
                "fetch-main bead should have no blocking dependencies"
            )

    def test_downstream_beads_each_have_one_blocks_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            _setup_bd_worktree(tmpdir, FORMULA_IN_BEADS)
            issues = self._pour_and_list(tmpdir)

            dependent_substrings = [
                "Rebase",
                "Run tests",
                "Merge and push",
                "Clean up after merging",
            ]
            for substr in dependent_substrings:
                matching = [i for i in issues if substr in i.get("title", "")]
                assert len(matching) >= 1, f"No bead found with title containing '{substr}'"
                bead = matching[0]
                blocks = [d for d in bead.get("dependencies", []) if d["type"] == "blocks"]
                assert len(blocks) == 1, (
                    f"Bead '{bead['title']}' should have exactly 1 blocking dependency, "
                    f"found {len(blocks)}"
                )
