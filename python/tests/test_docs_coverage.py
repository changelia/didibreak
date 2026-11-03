"""Every CLI flag and config key must be documented in configuration-python.md."""

import argparse
from pathlib import Path

import pytest

from didibreak.cli import build_parser
from didibreak.config import CONFIG_KEYS

DOC = Path(__file__).resolve().parents[2] / "docs" / "configuration-python.md"

pytestmark = pytest.mark.skipif(
    not DOC.is_file(),
    reason=f"{DOC} not found: this test needs the full repository checkout",
)


def _check_flags() -> list[str]:
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    check = subparsers.choices["check"]
    return [
        option
        for action in check._actions
        if action.help != argparse.SUPPRESS
        for option in action.option_strings
        if option not in ("-h", "--help")
    ]


def test_every_check_flag_is_documented() -> None:
    text = DOC.read_text(encoding="utf-8")

    missing = [flag for flag in _check_flags() if f"`{flag}" not in text]

    assert missing == []


def test_every_config_key_is_documented() -> None:
    text = DOC.read_text(encoding="utf-8")

    missing = [key for key in CONFIG_KEYS if f"`{key}`" not in text]

    assert missing == []
