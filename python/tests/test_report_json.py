"""JSON report: snapshot, schema validation and stable key order (task 18)."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from report_samples import check_snapshot, sample_report

from didibreak.report import ReportUsage
from didibreak.report.json import render_json, report_json

SCHEMA = Path(__file__).resolve().parents[2] / "spec" / "report.schema.json"
needs_schema = pytest.mark.skipif(
    not SCHEMA.is_file(), reason="needs the full repository checkout"
)


def validate(data: Any) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)


def test_json_snapshot() -> None:
    check_snapshot("report.json", render_json(sample_report()))


@needs_schema
def test_json_report_matches_the_schema() -> None:
    validate(report_json(sample_report()))


@needs_schema
def test_report_without_llm_and_findings_matches_the_schema() -> None:
    empty = replace(
        sample_report(),
        intent=None,
        findings=(),
        usage=ReportUsage(),
        skipped=(),
        removed=(),
    )
    validate(report_json(empty))


def test_json_keys_follow_the_documented_order() -> None:
    data = report_json(sample_report())

    assert list(data) == [
        "schema_version",
        "tool",
        "base",
        "intent",
        "findings",
        "summary",
        "usage",
    ]
    assert list(data["findings"][0]) == [
        "id",
        "function",
        "label",
        "reason",
        "confidence",
        "args",
        "kwargs",
        "before",
        "after",
        "test_file",
    ]
    assert list(data["summary"]["findings"]) == [
        "expected",
        "unexpected",
        "unclear",
        "new_function",
    ]


def test_json_outcomes_message_only_for_exceptions_and_null_before_for_new() -> None:
    findings = report_json(sample_report())["findings"]

    assert "message" not in findings[0]["after"]
    assert findings[2]["before"] is None
    assert findings[2]["after"]["message"].startswith("not enough values")
    assert findings[2]["kwargs"] == {"strict": "True"}


@needs_schema
def test_unknown_cost_is_null_and_valid_for_schema_version_1() -> None:
    report = replace(sample_report(), usage=ReportUsage(2, 1000, 600, None, None))

    data = report_json(report)

    assert data["schema_version"] == 1
    assert data["usage"]["cost_usd"] is None
    validate(data)
