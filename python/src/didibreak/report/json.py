"""The JSON report (Detailed Design section 6, spec/report.schema.json).

Keys are written in the order of the Detailed Design example, so the output
is stable from run to run. From the first release on, any new field needs a
new schema_version (Q17; owner decision 2026-11-09, task 21a review).

Version 2 (task 30) adds keys only: ``init_args`` and ``init_kwargs`` on
findings of instance methods, ``state`` on their outcomes, and
``summary.construction_dropped``. A report without method findings has the
same keys as version 1 apart from that summary count.
"""

import json
from typing import Any

from didibreak.compare import Finding
from didibreak.harness import Outcome
from didibreak.report import Report

SCHEMA_VERSION = 2
# Summary order of Detailed Design section 6 (the same labels as LABEL_ORDER).
SUMMARY_LABELS = ("expected", "unexpected", "unclear", "new_function")


def outcome_json(outcome: Outcome) -> dict[str, Any]:
    """An outcome as in the report: message only for exceptions (Q16).

    ``state`` (task 30) is the instance's attributes after the call, as
    text, only for instance methods.
    """
    data: dict[str, Any] = {
        "kind": outcome.kind,
        "type_name": outcome.type_name,
        "repr": outcome.repr,
    }
    if outcome.kind == "exception" and outcome.message is not None:
        data["message"] = outcome.message
    if outcome.state_repr is not None:
        data["state"] = outcome.state_repr
    return data


def finding_json(finding: Finding) -> dict[str, Any]:
    """One finding; ``before`` is null for new functions (Q13).

    A finding of an instance method also has ``init_args`` and
    ``init_kwargs``, the constructor arguments (task 30).
    """
    case = finding.case
    data: dict[str, Any] = {
        "id": finding.id,
        "function": finding.function,
        "label": finding.label,
        "reason": finding.reason or "",
        "confidence": finding.confidence,
        "args": list(case.args),
        "kwargs": dict(case.kwargs),
    }
    if case.init_args is not None:
        data["init_args"] = list(case.init_args)
        data["init_kwargs"] = dict(case.init_kwargs)
    data["before"] = None if finding.before is None else outcome_json(finding.before)
    data["after"] = outcome_json(finding.after)
    data["test_file"] = finding.test_file
    return data


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
            "type_mismatch_dropped": report.type_mismatch_dropped,
            "construction_dropped": report.construction_dropped,
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
