"""docs/ai-agents.md matches the code: snippet, labels and report keys (task 20)."""

import json
import re
from pathlib import Path

import pytest
from report_samples import sample_report

from didibreak.cli import AGENT_SNIPPET
from didibreak.report import LABEL_ORDER
from didibreak.report.json import report_json

DOC = Path(__file__).resolve().parents[2] / "docs" / "ai-agents.md"
pytestmark = pytest.mark.skipif(
    not DOC.is_file(), reason="needs the full repository checkout"
)


def block(language: str) -> str:
    match = re.search(rf"```{language}\n(.*?)```", DOC.read_text(), re.DOTALL)
    assert match, f"no {language} block in {DOC.name}"
    return match.group(1)


def test_snippet_is_the_init_agents_output() -> None:
    assert block("markdown") == AGENT_SNIPPET


def test_every_label_has_a_row_in_the_loop_table() -> None:
    text = DOC.read_text()

    for label in LABEL_ORDER:
        assert f"| `{label}` |" in text


def test_example_finding_uses_only_report_keys() -> None:
    example = json.loads(block("json"))["findings"][0]
    real = report_json(sample_report())["findings"][0]

    assert set(example) <= set(real)
    assert list(example) == [key for key in real if key in example]


def test_single_test_command_matches_the_generated_test_names() -> None:
    example = json.loads(block("json"))["findings"][0]
    qualname = example["function"].split("::")[1]

    assert f"-k {example['id']}" in DOC.read_text()
    blocks = re.findall(r"```console\n(.*?)```", DOC.read_text(), re.DOTALL)
    pytest_run = next(b for b in blocks if "$ pytest" in b)
    assert f"test_{qualname}_{example['id']}" in pytest_run
