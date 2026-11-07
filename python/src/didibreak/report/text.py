"""The text report (Detailed Design section 7).

Order: header (tool version, base) and changed functions, the cost estimate
(both printed before any LLM request), then the summary line, findings
grouped UNEXPECTED, UNCLEAR, EXPECTED, NEW-FUNCTION, skipped functions with
reasons, removed functions, refinement notes and the usage line last.
Colors only when the caller asks for them.
"""

from collections.abc import Sequence

from didibreak.compare import Finding
from didibreak.functions import Detection
from didibreak.harness import Outcome
from didibreak.report import Report

_COLORS = {"unexpected": "31", "unclear": "33", "expected": "32", "new_function": "36"}
_INDENT = 13


def _paint(text: str, label: str, color: bool) -> str:
    return f"\033[{_COLORS[label]}m{text}\033[0m" if color else text


def header_lines(
    version: str,
    base_ref: str,
    base_sha: str,
    excluded: Sequence[str],
    detection: Detection,
    max_functions: int,
    verbose: bool,
) -> list[str]:
    """Lines shown before any LLM request: version, base and what will run."""
    lines = [f"didibreak {version} · working tree vs {base_ref} ({base_sha[:12]})"]
    # Owner decision (task 05 review): exclusions are never silent.
    if excluded:
        noun = "file" if len(excluded) == 1 else "files"
        lines.append(f"{len(excluded)} {noun} excluded")
        lines += [f"  excluded: {path}" for path in excluded] if verbose else []
    lines += [f"skipped {f.path}: {f.reason}" for f in detection.skipped_files]
    new = sum(1 for function in detection.functions if function.kind == "new")
    lines.append(f"{len(detection.functions)} changed function(s) to check ({new} new)")
    if detection.skipped:
        lines.append(
            f"{len(detection.skipped)} function(s) skipped: not testable in v0.1"
        )
    if detection.limited:
        lines.append(
            f"{len(detection.limited)} more not checked "
            f"(max_functions = {max_functions})"
        )
    all_skipped = bool(detection.skipped) and not detection.functions
    if all_skipped:
        lines.append("Warning: checked 0 functions; all changed functions were skipped")
    if verbose:
        lines += [f"  {f.kind}: {f.report_name}" for f in detection.functions]
        lines += [f"  limit: {f.report_name}" for f in detection.limited]
    return lines


def _describe(outcome: Outcome | None) -> str:
    if outcome is None:
        return "(new function)"
    if outcome.kind == "exception":
        return f"raises {outcome.type_name}"
    return outcome.repr


def _finding_lines(finding: Finding, color: bool) -> list[str]:
    arguments = [*finding.case.args]
    arguments += [f"{key}={value}" for key, value in finding.case.kwargs.items()]
    heading = (finding.label or "").upper().replace("_", "-")
    label = _paint(f"{heading:<{_INDENT}}", finding.label or "unclear", color)
    lines = [
        f"  {label}{finding.function}({', '.join(arguments)})",
        f"  {'':<{_INDENT}}before {_describe(finding.before)} → "
        f"after {_describe(finding.after)}",
    ]
    if finding.reason:
        lines.append(f"  {'':<{_INDENT}}{finding.reason}")
    return lines


def _usage_line(report: Report) -> str:
    usage = report.usage
    reasoning = (
        f" ({usage.reasoning_tokens} reasoning)"
        if usage.reasoning_tokens is not None
        else ""
    )
    if usage.local:
        cost = " · cost $0 (local)"
    elif usage.cost_usd is not None:
        cost = f" · cost ${usage.cost_usd:.4f}"
    else:
        cost = ""
    return (
        f"LLM: {usage.calls} calls · {usage.input_tokens} input tokens · "
        f"{usage.output_tokens} output tokens{reasoning}{cost}"
    )


def results_text(report: Report, color: bool = False, llm: bool = True) -> str:
    """The report after the run.

    Args:
        report: The run's report.
        color: Use ANSI colors for the labels.
        llm: Show the LLM lines (usage, refinement); off for --cases-file runs.

    Returns:
        The text, ending with a newline.
    """
    lines = [
        f"{report.cases_run} cases · {len(report.findings)} behavior changes · "
        f"{report.flaky_dropped} flaky dropped"
    ]
    for _, group in report.by_label():
        for finding in group:
            lines += _finding_lines(finding, color)
    lines += [f"  skipped: {item.function} ({item.reason})" for item in report.skipped]
    if report.removed:
        lines.append(f"Removed: {', '.join(report.removed)}")
    if llm:
        if report.invalid_cases_dropped:
            lines.append(
                f"{report.invalid_cases_dropped} invalid cases dropped "
                "(not Python literals)"
            )
        if report.refined:
            lines.append(
                f"Refinement: {report.refined} function(s) got "
                f"{report.refinement_cases} more cases"
            )
        lines += [
            f"  refinement skipped: {item.function} ({item.reason})"
            for item in report.refinement_skipped
        ]
        # Detailed Design 7: the usage line comes last.
        lines.append(_usage_line(report))
    return "\n".join(lines) + "\n"
