"""Tests for US-001: Install beads (bd) and Dolt on the host."""

import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestDoltInstalled:
    """dolt binary is installed and runnable."""

    def test_dolt_on_path(self) -> None:
        assert shutil.which("dolt") is not None, "dolt binary not found on PATH"

    def test_dolt_version_succeeds(self) -> None:
        # dolt uses 'dolt version' (not --version)
        result = subprocess.run(
            ["dolt", "version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"dolt version failed: {result.stderr}"
        assert "dolt" in result.stdout.lower()


class TestBdInstalled:
    """bd (beads) CLI is installed and runnable."""

    def test_bd_on_path(self) -> None:
        assert shutil.which("bd") is not None, "bd binary not found on PATH"

    def test_bd_version_succeeds(self) -> None:
        result = subprocess.run(
            ["bd", "version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bd version failed: {result.stderr}"


class TestInstallScript:
    """scripts/install-deps.sh documents and automates installation."""

    def test_install_script_exists(self) -> None:
        assert (PROJECT_ROOT / "scripts" / "install-deps.sh").is_file()

    def test_install_script_is_executable(self) -> None:
        script = PROJECT_ROOT / "scripts" / "install-deps.sh"
        assert script.stat().st_mode & 0o111, "install-deps.sh should be executable"

    def test_install_script_mentions_dolt(self) -> None:
        content = (PROJECT_ROOT / "scripts" / "install-deps.sh").read_text()
        assert "dolt" in content.lower()

    def test_install_script_mentions_beads(self) -> None:
        content = (PROJECT_ROOT / "scripts" / "install-deps.sh").read_text()
        assert "beads" in content.lower() or "bd" in content.lower()
