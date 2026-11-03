"""Tests for the didibreak command-line entry points."""

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from didibreak import __version__
from didibreak.cli import main

EXPECTED_VERSION_LINE = f"didibreak {__version__}"


def test_version_flag_prints_name_and_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == EXPECTED_VERSION_LINE


def test_no_arguments_prints_help_and_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])

    assert exit_code == 0
    assert capsys.readouterr().out.startswith("usage: didibreak")


def test_unknown_option_exits_with_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--no-such-option"])

    assert exit_info.value.code == 2
    assert "unrecognized arguments: --no-such-option" in capsys.readouterr().err


def test_python_dash_m_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "didibreak", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == EXPECTED_VERSION_LINE


def test_console_script_prints_version() -> None:
    script = Path(sys.executable).parent / "didibreak"

    result = subprocess.run(
        [str(script), "--version"], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == EXPECTED_VERSION_LINE


def test_installed_metadata_version_matches_package_version() -> None:
    assert version("didibreak") == __version__
