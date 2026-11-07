"""docs/output-format.md matches the code: examples and every JSON key (task 18)."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from report_samples import sample_report

from didibreak.report.json import report_json
from didibreak.report.text import results_text

DOC = Path(__file__).resolve().parents[2] / "docs" / "output-format.md"
pytestmark = pytest.mark.skipif(
    not DOC.is_file(), reason="needs the full repository checkout"
)


def block(language: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(rf"```{language}\n(.*?)```", text, re.DOTALL)
    assert match, f"no {language} example in {DOC.name}"
    return match.group(1)


def key_paths(data: Any, prefix: str = "") -> Iterator[str]:
    """Dotted key paths; list items share the path ``name[]``."""
    if isinstance(data, dict):
        for key, value in data.items():
            yield prefix + key
            yield from key_paths(value, f"{prefix}{key}.")
    elif isinstance(data, list):
        for item in data:
            yield from key_paths(item, f"{prefix[:-1]}[].")


def test_json_example_is_the_report_of_the_sample_data() -> None:
    assert json.loads(block("json")) == report_json(sample_report())


def test_text_example_is_the_report_of_the_sample_data() -> None:
    assert block("text") == results_text(sample_report())


def test_every_json_key_is_documented() -> None:
    text = DOC.read_text(encoding="utf-8")
    paths = set(key_paths(report_json(sample_report())))
    # before has the same keys as after; the table documents them once.
    paths = {p for p in paths if not p.startswith("findings[].before.")}
    # kwargs keys are argument names from the checked code.
    paths = {p for p in paths if not p.startswith("findings[].kwargs.")}

    missing = sorted(p for p in paths if f"`{p}`" not in text)

    assert missing == []
