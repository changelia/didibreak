"""The JSON report (Detailed Design section 6, spec/report.schema.json).

Keys are written in the order of the Detailed Design example, so the output
is stable from run to run. Any new field needs a new schema_version (Q17).
"""

import json
from typing import Any

from didibreak.compare import Finding
from didibreak.harness import Outcome
from didibreak.report import Report

SCHEMA_VERSION = 1
# Summary order of Detailed Design section 6 (the same labels as LABEL_ORDER).
SUMMARY_LABELS = ("expected", "unexpected", "unclear", "new_function")


def outcome_json(outcome: Outcome) -> dict[str, Any]:
    """An outcome as in the report: message only for exceptions (Q16)."""
    data: dict[str, Any] = {
        "kind": outcome.kind,
        "type_name": outcome.type_name,
        "repr": outcome.repr,
    }
    if outcome.kind == "exception" and outcome.message is not None:
        data["message"] = outcome.message
    return data


def finding_json(finding: Finding) -> dict[str, Any]:
    """One finding; ``before`` is null for new functions (Q13)."""
    return {
        "id": finding.id,
        "function": finding.function,
        "label": finding.label,
        "reason": finding.reason or "",
        "confidence": finding.confidence,
        "args": list(finding.case.args),
        "kwargs": dict(finding.case.kwargs),
        "before": None if finding.before is None else outcome_json(finding.before),
        "after": outcome_json(finding.after),
        "test_file": finding.test_file,
    }


def report_json(report: Report) -> dict[str, Any]:
    """The whole report as JSON-ready data, keys in schema order."""
    counts = report.counts()
    usage = report.usage
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "didibreak", "version": report.version},
        "base": {"ref": report.base_ref, "sha": report.base_sha},
        "intent": report.intent,
        "findings": [finding_json(finding) for finding in report.findings],
        "summary": {
            "functions_checked": report.functions_checked,
            "cases_run": report.cases_run,
            "findings": {label: counts[label] for label in SUMMARY_LABELS},
            "flaky_dropped": report.flaky_dropped,
            "invalid_cases_dropped": report.invalid_cases_dropped,
            "skipped": [
                {"function": item.function, "reason": item.reason}
                for item in report.skipped
            ],
            "removed": [{"function": name} for name in report.removed],
        },
        "usage": {
            "calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": usage.cost_usd,
        },
    }


def render_json(report: Report) -> str:
    """The JSON report text, indented, with a final newline."""
    return json.dumps(report_json(report), indent=2, ensure_ascii=False) + "\n"
