"""The text report (Detailed Design section 7).

Order: header (tool version, base) and changed functions, the cost estimate
(both printed before any LLM request), then the summary line, findings
grouped UNEXPECTED, UNCLEAR, EXPECTED, NEW-FUNCTION, skipped functions with
reasons, removed functions, reproducing tests, refinement notes and the
usage line last.
Colors only when the caller asks for them.
"""

from collections.abc import Sequence

from didibreak.arguments import format_call
from didibreak.compare import Finding
from didibreak.functions import Detection
from didibreak.harness import Outcome
from didibreak.report import Report, SkippedItem

_COLORS = {"unexpected": "31", "unclear": "33", "expected": "32", "new_function": "36"}
_INDENT = 13
_SPACE_CONTROLS = "\t\n\r"


def printable(text: str) -> str:
    r"""Text safe for a terminal: no control characters (audit 35a, finding 8).

    LLM replies and the user's ``repr`` can contain escape sequences that
    move the cursor or change the terminal. Tabs and line breaks become
    spaces; any other C0 or C1 control character is shown as ``\xNN``.
    The JSON report keeps the text unchanged.

    Args:
        text: Text from the LLM or from the code under test.

    Returns:
        The text with control characters replaced.
    """
    return "".join(_printable_character(character) for character in text)


def _printable_character(character: str) -> str:
    code = ord(character)
    if character in _SPACE_CONTROLS:
        return " "
    if code < 0x20 or 0x7F <= code < 0xA0:
        return f"\\x{code:02x}"
    return character


def counted(count: int, noun: str) -> str:
    """``count`` with ``noun`` in the right number: "1 LLM call", "2 LLM calls"."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


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
        return f"raises {printable(outcome.type_name)}"
    return printable(outcome.repr)


def _finding_lines(finding: Finding, color: bool) -> list[str]:
    heading = (finding.label or "").upper().replace("_", "-")
    label = _paint(f"{heading:<{_INDENT}}", finding.label or "unclear", color)
    call = printable(
        format_call(finding.function, finding.case.args, finding.case.kwargs)
    )
    lines = [
        f"  {label}{call}",
        f"  {'':<{_INDENT}}before {_describe(finding.before)} → "
        f"after {_describe(finding.after)}",
    ]
    if finding.reason:
        lines.append(f"  {'':<{_INDENT}}{printable(finding.reason)}")
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
        cost = " · cost unknown"
    return (
        f"LLM: {counted(usage.calls, 'call')} · {usage.input_tokens} input tokens · "
        f"{usage.output_tokens} output tokens{reasoning}{cost}"
    )


def _item_line(prefix: str, item: SkippedItem) -> str:
    # Skip reasons can quote the provider; test calls hold LLM arguments.
    return f"  {prefix}: {printable(f'{item.function} ({item.reason})')}"


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
    if report.functions_checked == 0 and report.skipped:
        lines.append(
            "No function was checked: every changed function was skipped "
            "(reasons below)."
        )
    for _, group in report.by_label():
        for finding in group:
            lines += _finding_lines(finding, color)
    lines += [_item_line("skipped", item) for item in report.skipped]
    if report.removed:
        lines.append(f"Removed: {', '.join(report.removed)}")
    if report.test_files:
        lines.append(f"Reproducing tests: {', '.join(report.test_files)}")
    lines += [_item_line("no test", item) for item in report.no_tests]
    if report.type_mismatch_dropped:
        lines.append(
            f"{report.type_mismatch_dropped} findings dropped "
            "(inputs outside the type annotations)"
        )
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
            _item_line("refinement skipped", item) for item in report.refinement_skipped
        ]
        # Detailed Design 7: the usage line comes last.
        lines.append(_usage_line(report))
    return "\n".join(lines) + "\n"
