"""The GitHub Action's steps (github-action/didibreak_action.py, task 32)."""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ACTION = Path(__file__).resolve().parents[2] / "github-action"
pytestmark = pytest.mark.skipif(
    not ACTION.is_dir(), reason="needs the full repository checkout"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "didibreak_action", ACTION / "didibreak_action.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["didibreak_action"] = module
    spec.loader.exec_module(module)
    return module


action = _load() if ACTION.is_dir() else ModuleType("didibreak_action")

HOSTILE = (
    "@ghost [click](https://example.com) <img src=x onerror=alert(1)> "
    "**bold** #1 ```` </details> \u202eevil\u202c\nline ::error::boom"
)


def finding(**changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "30040f8bc543",
        "function": "app/prices.py::format_price",
        "label": "unexpected",
        "reason": "the minus sign is lost",
        "confidence": "high",
        "args": ["-250"],
        "kwargs": {},
        "before": {"kind": "return", "type_name": "builtins.str", "repr": "'-$2.50'"},
        "after": {"kind": "return", "type_name": "builtins.str", "repr": "'$2.50'"},
        "test_file": None,
    }
    return {**item, **changes}


def report(findings: list[dict[str, Any]], **summary: Any) -> dict[str, Any]:
    counts = {"expected": 0, "unexpected": 0, "unclear": 0, "new_function": 0}
    for item in findings:
        counts[item["label"]] += 1
    return {
        "schema_version": 2,
        "tool": {"name": "didibreak", "version": "0.4.0"},
        "base": {"ref": "abc", "sha": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"},
        "intent": None,
        "findings": findings,
        "summary": {
            "functions_checked": 1,
            "cases_run": 4,
            "findings": counts,
            "skipped": summary.get("skipped", []),
            "removed": [],
        },
        "usage": summary.get(
            "usage",
            {"calls": 2, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0041},
        ),
    }


def outside_code_blocks(markdown: str) -> str:
    """The text GitHub renders as Markdown: everything outside fenced blocks."""
    outside, fence = [], ""
    for line in markdown.split("\n"):
        if fence:
            if re.fullmatch(rf"{fence}`*\s*", line):
                fence = ""
            continue
        opening = re.match(r"(`{3,})", line)
        if opening:
            fence = opening[1]
            continue
        outside.append(line)
    assert not fence, "a code block is left open"
    return "\n".join(outside)


# --- comment -----------------------------------------------------------------


def test_clean_flattens_lines_and_escapes_invisible_characters() -> None:
    text = action.clean("a\nb\tc\u202ed\u200be\u2028f\x1b")

    assert text == "a b c\\u202ed\\u200be\\u2028f\\u001b"


def test_clean_cuts_long_lines() -> None:
    text = action.clean("x" * 1_000)

    assert len(text) == 600
    assert text.endswith("…")


def test_backticks_in_the_text_cannot_close_the_code_block() -> None:
    block = action.code_block(["a ```` b", "`````"])

    assert block.startswith("``````text\n")
    assert outside_code_blocks(block) == ""


def test_a_finding_shows_the_call_the_outcomes_and_the_reason() -> None:
    body = action.build_comment(report([finding()]), 1)

    assert "UNEXPECTED  app/prices.py::format_price(-250)" in body
    assert "before '-$2.50' → after '$2.50'" in body
    assert "the minus sign is lost" in body
    assert "**1 unexpected**" in body
    assert "cost $0.0041 (2 LLM calls)" in body
    assert body.startswith(action.MARKER)


def test_methods_constructors_and_exceptions_are_written_as_python() -> None:
    method = finding(
        function="app/bank.py::Account.deposit",
        init_args=["100"],
        init_kwargs={"limit": "5"},
        args=["-50"],
        before={"kind": "return", "repr": "None", "state": "{'balance': 100}"},
        after={"kind": "exception", "repr": "ValueError('no')"},
    )
    constructor = finding(
        function="app/order.py::Order.__init__",
        init_args=["0"],
        init_kwargs={},
        args=[],
    )

    body = action.build_comment(report([method, constructor]), 1)

    assert "app/bank.py::Account(100, limit=5).deposit(-50)" in body
    assert "before None → after raises ValueError('no')" in body
    assert "state before {'balance': 100} → after -" in body
    assert "app/order.py::Order(0)" in body


def test_expected_and_new_function_findings_are_only_counted() -> None:
    items = [finding(label="expected"), finding(label="new_function", before=None)]

    body = action.build_comment(report(items), 0)

    assert "No unexpected or unclear findings." in body
    assert "1 expected · 1 in new functions" in body
    assert "format_price" not in body


def test_hostile_text_is_never_rendered_as_markdown() -> None:
    items = [
        finding(
            function="app/x.py::f",
            reason=HOSTILE,
            args=[repr(HOSTILE)],
            after={"kind": "return", "repr": HOSTILE},
            label="unclear",
        )
    ]
    skipped = [{"function": "app/y.py::g", "reason": f"obvious I/O: {HOSTILE}"}]

    body = action.build_comment(report(items, skipped=skipped), 1)
    rendered = outside_code_blocks(body)

    for dangerous in ("@ghost", "<img", "https://", "[click]", "\u202e", "::error::"):
        assert dangerous not in rendered
    assert "\u202e" not in body
    assert "@ghost" in body  # still shown, inside a code block


def test_a_long_report_is_truncated_under_the_limit_with_a_note() -> None:
    items = [finding(args=[repr("x" * 500)], id=f"{n:012x}") for n in range(400)]

    body = action.build_comment(report(items), 1, limit=20_000)

    assert len(body) <= 20_000
    shown = body.count("UNEXPECTED  ")
    assert 0 < shown < 400
    assert f"Truncated: {400 - shown} more finding(s) not shown" in body
    outside_code_blocks(body)


def test_the_default_limit_stays_under_githubs_maximum() -> None:
    items = [finding(args=[repr("x" * 2_000)], id=f"{n:012x}") for n in range(400)]

    body = action.build_comment(report(items), 1)

    assert len(body) <= 65_536


def test_skip_reasons_are_counted_in_a_collapsed_section() -> None:
    skipped = [
        {"function": "a.py::f", "reason": "property"},
        {"function": "a.py::g", "reason": "property"},
        {"function": "a.py::h", "reason": "generator"},
    ]

    body = action.build_comment(report([], skipped=skipped), 0)

    assert "<summary>Skipped functions (3)</summary>" in body
    assert "   2  property" in body
    assert "1 function(s) checked, 3 skipped" in body


def test_an_unknown_cost_is_said_plainly() -> None:
    usage = {"calls": 1, "input_tokens": 1, "output_tokens": 1, "cost_usd": None}

    body = action.build_comment(report([], usage=usage), 0)

    assert "cost unknown (1 LLM calls; no price for this model)" in body


def test_an_error_run_says_so() -> None:
    assert "exit code 2" in action.build_comment(report([]), 2)
    missing = action.build_comment(None, 2)
    assert missing.startswith(action.MARKER)
    assert "did not produce a report (exit code 2)" in missing


def test_the_footer_keeps_only_version_and_hex_characters() -> None:
    hostile = report([])
    hostile["tool"]["version"] = "0.4.0 <b>@ghost</b>"
    hostile["base"]["sha"] = "abc<script>"

    body = action.build_comment(hostile, 0)

    assert "didibreak 0.4.0bghostb · compared with base abcc" in body


# --- logs ------------------------------------------------------------------


def test_untrusted_log_text_cannot_run_workflow_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action.print_untrusted("::add-mask::x\n::error::boom")

    lines = capsys.readouterr().out.splitlines()
    token = lines[0].removeprefix("::stop-commands::")
    assert len(token) == 32
    assert lines[1:3] == ["::add-mask::x", "::error::boom"]
    assert lines[3] == f"::{token}::"


def test_an_unknown_subcommand_is_a_usage_error() -> None:
    assert action.main(["deploy"]) == 2
