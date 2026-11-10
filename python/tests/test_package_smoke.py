"""scripts/package_smoke.py: the checks run against the installed package (task 23)."""

import importlib.util
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def silent_provider() -> Iterator[str]:
    """A local server that accepts connections and never answers."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        yield f"http://127.0.0.1:{server.getsockname()[1]}/v1"


def test_a_stalled_provider_fails_fast_instead_of_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression (task 26): a stalled connection used to block the check
    # for up to 300 s per command, which looked like a hung test suite.
    monkeypatch.setattr(smoke, "fake_provider", silent_provider)
    started = time.monotonic()

    problems = smoke.run_checks(DIDIBREAK, __version__, tmp_path, timeout=3)

    assert time.monotonic() - started < 30
    assert problems == ["check exited -9, expected 1: did not finish within 3 s"]


def test_every_command_has_a_bounded_run_time() -> None:
    assert 0 < smoke.COMMAND_TIMEOUT_SECONDS <= 60
