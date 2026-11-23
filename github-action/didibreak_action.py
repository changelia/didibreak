"""Steps of the didibreak GitHub Action (``action.yml`` next to this file).

Standard library only: the action runs this file with the interpreter it
was given, before and after didibreak is installed. Every value that comes
from the pull request (its title and body, function names, reprs of values,
LLM reasons) is untrusted, so the comment shows it only inside fenced code
blocks, where GitHub renders no Markdown, HTML, links or @mentions.

Subcommands, each reading its inputs from ``DIDIBREAK_ACTION_*`` variables:

- ``comment``: write the pull request comment from the report.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MARKER = "<!-- didibreak-action-comment -->"
# GitHub rejects comments over 65,536 characters; stay well below it.
MAX_COMMENT_CHARACTERS = 60_000
MAX_LINE_CHARACTERS = 600
SHOWN_LABELS = ("unexpected", "unclear")


def env(name: str, default: str = "") -> str:
    """The value of ``DIDIBREAK_ACTION_<name>``, stripped, or ``default``."""
    return os.environ.get(f"DIDIBREAK_ACTION_{name}", default).strip() or default


# --- comment -----------------------------------------------------------------


_ESCAPED_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")


def clean(text: str) -> str:
    r"""One line of untrusted text, safe inside a fenced code block.

    Line breaks and tabs become spaces; other control and format
    characters (bidirectional overrides, zero-width spaces, line
    separators) become ``\uXXXX`` escapes so they cannot hide or reorder
    text. Lines longer than 600 characters are cut with an ellipsis.
    """
    characters = []
    for character in text:
        if character in "\r\n\t":
            characters.append(" ")
        elif unicodedata.category(character) in _ESCAPED_CATEGORIES:
            characters.append(f"\\u{ord(character):04x}")
        else:
            characters.append(character)
    line = "".join(characters)
    if len(line) > MAX_LINE_CHARACTERS:
        line = line[: MAX_LINE_CHARACTERS - 1] + "…"
    return line


def code_block(lines: Sequence[str]) -> str:
    """Lines in a fenced code block that no line can close.

    The fence is one backtick longer than the longest run of backticks in
    the text (at least three), so the text can never end the block early.
    """
    text = "\n".join(lines)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def call_text(finding: Mapping[str, Any]) -> str:
    """The call as Python: ``path::f(1)``, ``path::C(2).m(1)`` or ``path::C(2)``."""
    path, _, qualname = str(finding.get("function", "")).partition("::")
    arguments = _arguments(finding.get("args", []), finding.get("kwargs", {}))
    if "init_args" not in finding:
        return f"{path}::{qualname}({arguments})"
    owner, _, method = qualname.rpartition(".")
    built = _arguments(finding.get("init_args", []), finding.get("init_kwargs", {}))
    if method == "__init__":
        return f"{path}::{owner}({built})"
    return f"{path}::{owner}({built}).{method}({arguments})"


def _arguments(args: Sequence[Any], kwargs: Mapping[str, Any]) -> str:
    named = [f"{name}={value}" for name, value in kwargs.items()]
    return ", ".join([*map(str, args), *named])


def outcome_text(outcome: Mapping[str, Any] | None) -> str:
    """``'x'``, ``raises ValueError('bad')``, ``timeout`` or ``(new function)``."""
    if outcome is None:
        return "(new function)"
    if outcome.get("kind") == "exception":
        return f"raises {outcome.get('repr', '')}"
    if outcome.get("kind") == "timeout":
        return "timeout"
    return str(outcome.get("repr", ""))


def finding_lines(finding: Mapping[str, Any]) -> list[str]:
    """The lines of one finding in the comment, all cleaned."""
    label = str(finding.get("label", "")).upper()
    before, after = finding.get("before"), finding.get("after")
    lines = [
        f"{label:<12}{call_text(finding)}",
        f"{'':12}before {outcome_text(before)} → after {outcome_text(after)}",
    ]
    states = [(side or {}).get("state") for side in (before, after)]
    if any(state is not None for state in states):
        shown = [state if state is not None else "-" for state in states]
        lines.append(f"{'':12}state before {shown[0]} → after {shown[1]}")
    if finding.get("reason"):
        lines.append(f"{'':12}{finding['reason']}")
    return [clean(line) for line in lines]


def summary_line(report: Mapping[str, Any]) -> str:
    """The first line: counts and cost, numbers only (trusted)."""
    summary = report.get("summary", {})
    counts = summary.get("findings", {})
    checked = int(summary.get("functions_checked", 0))
    skipped = len(summary.get("skipped", []))
    parts = [
        f"**{int(counts.get('unexpected', 0))} unexpected**",
        f"**{int(counts.get('unclear', 0))} unclear**",
        f"{int(counts.get('expected', 0))} expected",
        f"{int(counts.get('new_function', 0))} in new functions",
    ]
    functions = f"{checked} function(s) checked, {skipped} skipped"
    return f"{' · '.join(parts)} — {functions} — {cost_text(report)}"


def cost_text(report: Mapping[str, Any]) -> str:
    """The LLM use of the run, for example ``cost $0.0041 (3 LLM calls)``."""
    usage = report.get("usage", {})
    calls = int(usage.get("calls", 0))
    cost = usage.get("cost_usd")
    if isinstance(cost, int | float):
        return f"cost ${float(cost):.4f} ({calls} LLM calls)"
    return f"cost unknown ({calls} LLM calls; no price for this model)"


def skipped_section(report: Mapping[str, Any]) -> str:
    """A collapsed list of skip reasons with counts, most frequent first."""
    skipped = report.get("summary", {}).get("skipped", [])
    if not skipped:
        return ""
    reasons = Counter(str(item.get("reason", "")) for item in skipped).most_common()
    lines = [clean(f"{count:>4}  {reason}") for reason, count in reasons[:50]]
    if len(reasons) > 50:
        lines.append(f"... {len(reasons) - 50} more reasons")
    return (
        f"\n<details><summary>Skipped functions ({len(skipped)})</summary>\n\n"
        f"{code_block(lines)}\n\n</details>\n"
    )


def build_comment(
    report: Mapping[str, Any] | None,
    exit_code: int,
    limit: int = MAX_COMMENT_CHARACTERS,
) -> str:
    """The pull request comment for a report.

    Args:
        report: The parsed JSON report, or None when didibreak wrote none.
        exit_code: didibreak's exit code.
        limit: Maximum length of the comment.

    Returns:
        Markdown that starts with the hidden marker. Only fixed text and
        numbers are outside code blocks.
    """
    head = f"{MARKER}\n### didibreak\n\n"
    if report is None:
        return head + (
            f"didibreak did not produce a report (exit code {int(exit_code)}). "
            "The reason is in the job log.\n"
        )
    parts = [head + summary_line(report) + "\n"]
    if exit_code == 2:
        parts.append(
            "\nSome changed functions could not be checked because of an error "
            "(exit code 2); the reasons are under Skipped and in the job log.\n"
        )
    findings = [f for f in report.get("findings", []) if f.get("label") in SHOWN_LABELS]
    return _fit(parts, findings, skipped_section(report) + _footer(report), limit)


def _footer(report: Mapping[str, Any]) -> str:
    version = str(report.get("tool", {}).get("version", ""))
    version = re.sub(r"[^0-9A-Za-z.+-]", "", version)
    base = re.sub(r"[^0-9a-f]", "", str(report.get("base", {}).get("sha", "")))[:12]
    return (
        f"\n<sub>didibreak {version} · compared with base {base} · "
        "full report: job log and the workflow run's artifacts</sub>\n"
    )


def _fit(
    parts: list[str],
    findings: Sequence[Mapping[str, Any]],
    tail: str,
    limit: int,
) -> str:
    """Join the comment, leaving findings out from the end until it fits."""
    entries = [finding_lines(finding) for finding in findings]
    head = "".join(parts)
    for shown in range(len(entries), -1, -1):
        body = head + _findings_section(entries[:shown], len(entries)) + tail
        if len(body) <= limit:
            return body
    return head[:limit]


def _findings_section(entries: Sequence[Sequence[str]], total: int) -> str:
    if not total:
        return "\nNo unexpected or unclear findings.\n"
    lines = [line for entry in entries for line in entry]
    text = f"\n**Unexpected and unclear findings ({total})**\n\n"
    if entries:
        text += code_block(lines) + "\n"
    if len(entries) < total:
        text += (
            f"\n_Truncated: {total - len(entries)} more finding(s) not shown "
            "(GitHub comment size limit). See the job log and the "
            "workflow run's artifacts._\n"
        )
    return text


def _comment_main() -> int:
    exit_code = int(env("EXIT_CODE", "2"))
    report = _read_report(Path(env("REPORT", "didibreak-report.json")))
    body = build_comment(report, exit_code)
    output = Path(env("TEMP", ".")) / "didibreak-comment.md"
    output.write_text(body, encoding="utf-8")
    _write_output("comment", str(output))
    if report is not None:
        counts = report.get("summary", {}).get("findings", {})
        _write_output("unexpected", str(int(counts.get("unexpected", 0))))
        _write_output("unclear", str(int(counts.get("unclear", 0))))
    print_untrusted(json.dumps(report, indent=2) if report is not None else "no report")
    return 0


def _read_report(path: Path) -> dict[str, Any] | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


# --- GitHub Actions helpers --------------------------------------------------


def print_untrusted(text: str) -> None:
    """Print text to the job log with workflow commands turned off.

    A line such as ``::add-mask::`` or ``::error::`` inside a repr or an
    LLM reason would otherwise be run as a workflow command.
    """
    token = secrets.token_hex(16)
    print(f"::stop-commands::{token}")
    print(text)
    print(f"::{token}::", flush=True)


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            output.write(f"{name}={value}\n")


COMMANDS = {
    "comment": _comment_main,
}


def main(arguments: Sequence[str]) -> int:
    """Run one subcommand; returns the process exit code."""
    if len(arguments) != 1 or arguments[0] not in COMMANDS:
        print(f"usage: didibreak_action.py {{{','.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    return COMMANDS[arguments[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
