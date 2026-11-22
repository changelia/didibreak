"""The GitHub issue templates ask for what a bug report needs (task 35c)."""

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / ".github" / "ISSUE_TEMPLATE"
pytestmark = pytest.mark.skipif(
    not TEMPLATES.is_dir(), reason="needs the full repository checkout"
)


def field_ids(name: str) -> list[str]:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    return re.findall(r"^    id: (\S+)$", text, flags=re.MULTILINE)


def test_bug_report_asks_for_version_python_os_command_and_output() -> None:
    ids = field_ids("bug_report.yml")

    assert {"version", "python", "os", "command", "output"} <= set(ids)


def test_bug_report_tells_users_to_remove_api_keys() -> None:
    text = (TEMPLATES / "bug_report.yml").read_text(encoding="utf-8")

    assert "Remove API keys" in text


def test_feature_request_exists_with_a_problem_and_a_proposal() -> None:
    assert {"problem", "proposal"} <= set(field_ids("feature_request.yml"))


def test_config_links_the_docs() -> None:
    text = (TEMPLATES / "config.yml").read_text(encoding="utf-8")

    assert "https://github.com/changelia/didibreak/tree/main/docs" in text


def test_skipped_or_wrong_finding_asks_for_shape_report_and_expectation() -> None:
    ids = field_ids("skipped_or_wrong_finding.yml")

    assert {"version", "function", "report", "expected"} <= set(ids)


def test_skipped_or_wrong_finding_tells_users_to_remove_secrets() -> None:
    text = (TEMPLATES / "skipped_or_wrong_finding.yml").read_text(encoding="utf-8")

    assert "Remove API" in text
    assert "keys, passwords and other secrets" in text


REPOSITORY_LABELS = {
    "accessibility",
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "invalid",
    "question",
    "wontfix",
}


@pytest.mark.parametrize(
    "name", ["bug_report.yml", "feature_request.yml", "skipped_or_wrong_finding.yml"]
)
def test_templates_use_only_existing_labels(name: str) -> None:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    line = re.search(r"^labels: \[(.*)\]$", text, flags=re.MULTILINE)

    assert line is not None
    labels = {label.strip().strip('"') for label in line.group(1).split(",")}
    assert labels <= REPOSITORY_LABELS


def test_a_template_without_labels_is_caught() -> None:
    assert re.search(r"^labels: \[(.*)\]$", "name: x\n", flags=re.MULTILINE) is None
