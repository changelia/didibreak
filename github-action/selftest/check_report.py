"""Fail the action's self-test when the fixture was not checked.

The self-test (.github/workflows/github-action.yml) changes ``format_price``
so that it loses the minus sign, then runs the action with ``cases.json``.
A run that checks nothing must not pass: on PR #44 ``max_functions`` cut
the fixture, and the job passed with no finding (owner decision
2026-11-24). Usage: ``python check_report.py REPORT.json``; exit code 1
with the reasons when the report does not show the expected finding.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

FIXTURE = "github-action/selftest/prices.py::format_price"
EXPECTED_BEFORE = "'-$2.50'"
EXPECTED_AFTER = "'$2.50'"


def problems(report: Mapping[str, Any]) -> list[str]:
    """Why the report does not show the fixture's lost minus sign.

    Args:
        report: didibreak's JSON report.

    Returns:
        One line per problem; empty when the fixture was checked and
        ``format_price(-250)`` changed from ``'-$2.50'`` to ``'$2.50'``.
    """
    summary = report.get("summary", {})
    skipped = [
        item.get("reason", "")
        for item in summary.get("skipped", [])
        if item.get("function") == FIXTURE
    ]
    if skipped:
        return [f"{FIXTURE} was skipped: {', '.join(skipped)}"]
    findings = [f for f in report.get("findings", []) if f.get("function") == FIXTURE]
    if not findings:
        return [f"{FIXTURE} produced no finding (functions checked: "
                f"{summary.get('functions_checked', 0)})"]  # fmt: skip
    for finding in findings:
        if _is_lost_minus_sign(finding):
            return []
    return [f"{FIXTURE}(-250) is not among the findings with '-$2.50' -> '$2.50'"]


def _is_lost_minus_sign(finding: Mapping[str, Any]) -> bool:
    before = finding.get("before") or {}
    after = finding.get("after") or {}
    return (
        finding.get("args") == ["-250"]
        and before.get("repr") == EXPECTED_BEFORE
        and after.get("repr") == EXPECTED_AFTER
    )


def main(arguments: Sequence[str]) -> int:
    """Check the report named in ``arguments``; returns the exit code."""
    if len(arguments) != 1:
        print("usage: check_report.py REPORT.json", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"self-test: no readable report ({error})")
        return 1
    found = problems(report)
    for problem in found:
        print(f"self-test: {problem}")
    if not found:
        print(f"self-test: {FIXTURE} was checked and lost the minus sign, as expected.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
