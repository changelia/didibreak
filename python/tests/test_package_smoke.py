"""scripts/package_smoke.py: the checks run against the installed package (task 23)."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from didibreak import __version__

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_smoke.py"
DIDIBREAK = [sys.executable, "-m", "didibreak"]


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("package_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load_script()


def test_checks_pass_against_the_current_package(tmp_path: Path) -> None:
    assert smoke.run_checks(DIDIBREAK, __version__, tmp_path) == []


def test_a_wrong_version_is_reported(tmp_path: Path) -> None:
    problems = smoke.run_checks(DIDIBREAK, "9.9.9", tmp_path)

    assert problems == [f"--version printed 'didibreak {__version__}', expected 9.9.9"]


def test_a_check_without_the_finding_is_reported() -> None:
    clean = subprocess.CompletedProcess(["didibreak"], 0, stdout="{}", stderr="")

    assert smoke.check_report(clean)[0].startswith("check exited 0, expected 1")


def test_the_fixture_changes_only_the_lower_bound(tmp_path: Path) -> None:
    repository = smoke.make_repository(tmp_path / "repo")

    diff = subprocess.run(
        ["git", "-C", str(repository), "diff", "--stat"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "calc.py | 2 +-" in diff


def test_a_dist_folder_needs_one_wheel_and_one_sdist(tmp_path: Path) -> None:
    (tmp_path / "didibreak-0.1.0-py3-none-any.whl").write_text("")

    with pytest.raises(SystemExit, match="expected one wheel and one sdist"):
        smoke.packages(tmp_path)


def test_the_version_comes_from_the_wheel_name(tmp_path: Path) -> None:
    (tmp_path / "didibreak-0.1.0-py3-none-any.whl").write_text("")
    (tmp_path / "didibreak-0.1.0.tar.gz").write_text("")

    assert smoke.packages(tmp_path)[2] == "0.1.0"
