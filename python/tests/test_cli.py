"""Tests for the didibreak command-line entry points."""

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from didibreak import __version__
from didibreak.cli import is_supported_platform, main

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


@pytest.mark.parametrize(
    "argv", [["check"], ["init-agents"], ["--version"], []], ids=str
)
def test_windows_exits_2_with_one_line_before_any_work(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def no_work(*args: object, **kwargs: object) -> None:
        raise AssertionError("didibreak did work on Windows")

    monkeypatch.setattr("didibreak.cli.build_parser", no_work)

    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert "Windows is not supported" in captured.err
    assert "Linux and macOS" in captured.err


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_linux_and_macos_are_supported(platform: str) -> None:
    assert is_supported_platform(platform)


def test_windows_is_not_supported() -> None:
    assert not is_supported_platform("win32")
