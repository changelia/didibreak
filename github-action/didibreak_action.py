"""Steps of the didibreak GitHub Action (``action.yml`` next to this file).

Standard library only: the action runs this file with the interpreter it
was given, before and after didibreak is installed. Every value that comes
from the pull request (its title and body, function names, reprs of values,
LLM reasons) is untrusted, so the comment shows it only inside fenced code
blocks, where GitHub renders no Markdown, HTML, links or @mentions.

Subcommands, each reading its inputs from ``DIDIBREAK_ACTION_*`` variables:

- ``preflight``: decide whether the run can go ahead (event, API key).
- ``run``: run ``didibreak check --format json`` and keep the report.
- ``comment``: write the pull request comment from the report.
- ``post``: create the comment, or update the one posted before.
- ``finish``: the step's exit code for the chosen mode.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MARKER = "<!-- didibreak-action-comment -->"
# GitHub rejects comments over 65,536 characters; stay well below it.
MAX_COMMENT_CHARACTERS = 60_000
MAX_LINE_CHARACTERS = 600
MAX_INTENT_CHARACTERS = 4_000
SHOWN_LABELS = ("unexpected", "unclear")
KEY_VARIABLES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
LOCAL_PROVIDERS = ("ollama", "lmstudio")
MODES = ("report-only", "fail-on-unexpected")
NO_COMMIT_INTENT = "--no-commit-intent"
OLD_DIDIBREAK_MESSAGE = (
    "didibreak: intent-source fixed needs a didibreak version with "
    "--no-commit-intent, which keeps the pull request's commit messages out "
    "of the intent. Set didibreak-version to a newer release; the check "
    "did not run."
)
INTENT_SOURCES = ("pr", "commits", "fixed")
NO_KEY_MESSAGE = (
    "didibreak skipped: no API key. Pull requests from forks get no "
    "repository secrets, so the action cannot call the LLM for them; "
    "this is expected and the job passes. For pull requests from this "
    "repository, add the key as a repository secret and pass it as "
    "the api-key input."
)
WRONG_EVENT_MESSAGE = (
    "didibreak: this action runs only on the pull_request event. "
    "Never use pull_request_target with it: that event runs the pull "
    "request's code with the repository's secrets, so a fork could steal "
    "the API key."
)


def env(name: str, default: str = "") -> str:
    """The value of ``DIDIBREAK_ACTION_<name>``, stripped, or ``default``."""
    return os.environ.get(f"DIDIBREAK_ACTION_{name}", default).strip() or default


# --- preflight ---------------------------------------------------------------


def preflight(values: Mapping[str, str]) -> tuple[str, str]:
    """Decide whether the action can run.

    Args:
        values: ``event``, ``mode``, ``intent_source``, ``intent``,
            ``provider``, ``has_key`` ("true" / "false") and ``cases_file``.

    Returns:
        ``("run", "")``, ``("skip", message)`` for a pull request without
        an API key (forks), or ``("error", message)`` for a wrong event or
        an invalid input.
    """
    if values["event"] != "pull_request":
        return "error", WRONG_EVENT_MESSAGE
    if values["mode"] not in MODES:
        return "error", f"didibreak: mode must be one of {', '.join(MODES)}."
    if values["intent_source"] not in INTENT_SOURCES:
        sources = ", ".join(INTENT_SOURCES)
        return "error", f"didibreak: intent-source must be one of {sources}."
    if values["intent_source"] == "fixed" and not values["intent"]:
        return "error", "didibreak: intent-source fixed needs the intent input."
    provider = values["provider"]
    if provider not in KEY_VARIABLES and provider not in LOCAL_PROVIDERS:
        known = ", ".join([*KEY_VARIABLES, *LOCAL_PROVIDERS])
        return "error", f"didibreak: provider must be one of {known}."
    needs_key = provider in KEY_VARIABLES and not values["cases_file"]
    if needs_key and values["has_key"] != "true":
        return "skip", NO_KEY_MESSAGE
    return "run", ""


def _preflight_main() -> int:
    decision, message = preflight(
        {
            "event": env("EVENT"),
            "mode": env("MODE", "report-only"),
            "intent_source": env("INTENT_SOURCE", "pr"),
            "intent": env("INTENT"),
            "provider": env("PROVIDER", "openai"),
            "has_key": "true" if env("API_KEY") else "false",
            "cases_file": env("CASES_FILE"),
        }
    )
    _write_output("decision", decision)
    if env("API_KEY"):
        # Inputs from secrets are masked already; this covers other sources.
        print(f"::add-mask::{env('API_KEY')}")
    if decision == "skip":
        print(f"::notice title=didibreak skipped::{message}")
        _append_summary(message)
    elif decision == "error":
        print(f"::error title=didibreak::{message}")
        return 1
    return 0


# --- run -------------------------------------------------------------------


def pull_request_intent(title: str, body: str) -> str:
    """The intent text from a pull request, at most 4,000 characters."""
    text = title.strip()
    if body.strip():
        text = f"{text}\n\n{body.strip()}"
    return text[:MAX_INTENT_CHARACTERS]


def check_command(values: Mapping[str, str]) -> list[str]:
    """The ``didibreak check`` command line for the action's inputs.

    Args:
        values: ``didibreak``, ``base``, ``python``, ``output_dir``,
            ``provider``, ``model``, ``max_cost``, ``max_tokens``,
            ``intent_source``, ``intent``, ``pr_title``, ``pr_body`` and
            ``cases_file``.

    Returns:
        The argument list; untrusted text is one argument, never shell code.
    """
    command = [values["didibreak"], "check", "--base", values["base"]]
    command += ["--format", "json", "--yes", "--fail-on", "unexpected"]
    command += ["--python", values["python"], "--output-dir", values["output_dir"]]
    command += ["--provider", values["provider"]]
    command += ["--max-cost", values["max_cost"], "--max-tokens", values["max_tokens"]]
    if values["model"]:
        command += ["--model", values["model"]]
    intent = _intent(values)
    if intent:
        command += ["--intent", intent]
    if values["intent_source"] == "fixed":
        # The pull request's author writes the commit messages too, so a
        # fixed intent leaves them out (owner decision 2026-11-24).
        command.append(NO_COMMIT_INTENT)
    if values["cases_file"]:
        command += ["--cases-file", values["cases_file"]]
    return command


def _intent(values: Mapping[str, str]) -> str:
    if values["intent_source"] == "fixed":
        return values["intent"]
    if values["intent_source"] == "pr":
        return pull_request_intent(values["pr_title"], values["pr_body"])
    return ""


_HIDDEN_VARIABLES = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "ACTIONS_RUNTIME_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
)


def check_environment(
    environment: Mapping[str, str], provider: str, api_key: str
) -> dict[str, str]:
    """The environment for didibreak: the key in the provider's variable.

    The action's own variables (the key among them) and GitHub's tokens
    are not passed on: didibreak runs the pull request's code.
    """
    child = {
        name: value
        for name, value in environment.items()
        if not name.startswith("DIDIBREAK_ACTION_") and name not in _HIDDEN_VARIABLES
    }
    variable = KEY_VARIABLES.get(provider)
    if variable and api_key:
        child[variable] = api_key
    return child


def run_check(
    values: Mapping[str, str], api_key: str, temporary: Path
) -> tuple[int, Path]:
    """Run ``didibreak check`` and keep its JSON report.

    Returns:
        didibreak's exit code (2 without running it when a fixed intent
        needs ``--no-commit-intent`` and the installed didibreak lacks it)
        and the report path.
    """
    child = check_environment(os.environ, values["provider"], api_key)
    report = temporary / "didibreak-report.json"
    if values["intent_source"] == "fixed" and not _has_option(
        values["didibreak"], NO_COMMIT_INTENT, child
    ):
        print(f"::error title=didibreak::{OLD_DIDIBREAK_MESSAGE}")
        report.write_text("", encoding="utf-8")
        return 2, report
    with report.open("w", encoding="utf-8") as stdout:
        result = subprocess.run(
            check_command(values), stdout=stdout, stderr=subprocess.PIPE,
            env=child, text=True, check=False,
        )  # fmt: skip
    print_untrusted(result.stderr)
    return result.returncode, report


def _has_option(didibreak: str, option: str, child: Mapping[str, str]) -> bool:
    result = subprocess.run(
        [didibreak, "check", "--help"], capture_output=True,
        env=child, text=True, check=False,
    )  # fmt: skip
    return option in result.stdout


def _run_main() -> int:
    temporary = Path(env("TEMP", "."))
    values = {
        "didibreak": env("DIDIBREAK", "didibreak"),
        "base": env("BASE"),
        "python": env("PYTHON", sys.executable),
        "output_dir": str(temporary / "didibreak-output"),
        "provider": env("PROVIDER", "openai"),
        "model": env("MODEL"),
        "max_cost": env("MAX_COST", "0.50"),
        "max_tokens": env("MAX_TOKENS", "200000"),
        "intent_source": env("INTENT_SOURCE", "pr"),
        "intent": env("INTENT"),
        "pr_title": os.environ.get("DIDIBREAK_ACTION_PR_TITLE", ""),
        "pr_body": os.environ.get("DIDIBREAK_ACTION_PR_BODY", ""),
        "cases_file": env("CASES_FILE"),
    }
    exit_code, report = run_check(values, env("API_KEY"), temporary)
    _write_output("exit-code", str(exit_code))
    _write_output("report", str(report))
    return 0


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
        f"\n<sub>didibreak `{version}` · compared with base `{base}` · "
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


# --- post --------------------------------------------------------------------


def find_comment(comments: Sequence[Mapping[str, Any]]) -> int | None:
    """The id of the action's earlier comment, or None.

    Only a comment by a bot account counts, so a person who pastes the
    marker into their own comment cannot make the action edit it.
    """
    for comment in comments:
        user = comment.get("user") or {}
        if (
            str(comment.get("body", "")).startswith(MARKER)
            and user.get("type") == "Bot"
        ):
            return int(comment["id"])
    return None


def _request(method: str, url: str, token: str, data: Any = None) -> Any:
    request = urllib.request.Request(
        url,
        method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "didibreak-action",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def post_comment(api: str, repository: str, number: int, token: str, body: str) -> str:
    """Update the action's comment on the pull request, or create it.

    Returns:
        ``updated`` or ``created``.
    """
    issue = f"{api}/repos/{repository}/issues/{number}/comments"
    comments: list[Mapping[str, Any]] = []
    for page in range(1, 31):
        batch = _request("GET", f"{issue}?per_page=100&page={page}", token)
        if not isinstance(batch, list):
            break
        comments += batch
        if len(batch) < 100:
            break
    existing = find_comment(comments)
    if existing is not None:
        url = f"{api}/repos/{repository}/issues/comments/{existing}"
        _request("PATCH", url, token, {"body": body})
        return "updated"
    _request("POST", issue, token, {"body": body})
    return "created"


def _post_main() -> int:
    body = Path(env("COMMENT")).read_text(encoding="utf-8")
    try:
        result = post_comment(
            env("API_URL", "https://api.github.com"),
            env("REPOSITORY"),
            int(env("PR_NUMBER")),
            env("GITHUB_TOKEN"),
            body,
        )
    except urllib.error.HTTPError as error:
        print(
            "::warning title=didibreak::Could not post the comment "
            f"(HTTP {error.code}). The workflow needs 'permissions: "
            "pull-requests: write'; pull requests from forks get a read-only "
            "token, so no comment can be posted for them."
        )
        return 0
    print(f"didibreak: pull request comment {result}.")
    return 0


# --- finish ------------------------------------------------------------------


def finish(mode: str, exit_code: int, has_report: bool) -> tuple[int, str]:
    """The step's exit code and a message for the job log.

    ``report-only`` never fails the job; problems become warnings.
    ``fail-on-unexpected`` fails on unexpected findings (didibreak's exit
    code 1 with ``--fail-on unexpected``) and on errors (exit code 2).
    """
    if exit_code == 0 and has_report:
        return 0, ""
    if exit_code == 1:
        problem = "didibreak found unexpected behavior changes."
    else:
        problem = f"didibreak ended with an error (exit code {exit_code}); see the log."
    return (1 if mode == "fail-on-unexpected" else 0), problem


def _finish_main() -> int:
    code, message = finish(
        env("MODE", "report-only"),
        int(env("EXIT_CODE", "2")),
        _read_report(Path(env("REPORT", "didibreak-report.json"))) is not None,
    )
    if message:
        print(f"::{'error' if code else 'warning'} title=didibreak::{message}")
    return code


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


def _append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as summary:
            summary.write(f"{text}\n")


COMMANDS = {
    "preflight": _preflight_main,
    "run": _run_main,
    "comment": _comment_main,
    "post": _post_main,
    "finish": _finish_main,
}


def main(arguments: Sequence[str]) -> int:
    """Run one subcommand; returns the process exit code."""
    if len(arguments) != 1 or arguments[0] not in COMMANDS:
        print(f"usage: didibreak_action.py {{{','.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    return COMMANDS[arguments[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
