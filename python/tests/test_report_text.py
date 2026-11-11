"""Text report: snapshot, label order, colors and the usage line (task 18)."""

import dataclasses

import pytest
from report_samples import check_snapshot, sample_report

from didibreak.harness import Case, Outcome
from didibreak.report import Report, ReportUsage, SkippedItem
from didibreak.report.json import report_json
from didibreak.report.text import counted, printable, results_text


def test_text_snapshot() -> None:
    check_snapshot("report.txt", results_text(sample_report()))


def test_text_groups_unexpected_first_then_unclear_expected_new() -> None:
    text = results_text(sample_report())

    unexpected = text.index("UNEXPECTED")
    expected = text.index("EXPECTED   ")
    new = text.index("NEW-FUNCTION")
    assert unexpected < expected < new


def test_text_colors_only_when_asked() -> None:
    assert "\033[" not in results_text(sample_report())
    colored = results_text(sample_report(), color=True)
    assert "\033[31mUNEXPECTED" in colored
    assert "\033[36mNEW-FUNCTION" in colored


def test_text_without_llm_has_no_usage_lines() -> None:
    text = results_text(sample_report(), llm=False)

    assert "LLM:" not in text
    assert "Refinement" not in text
    assert text.startswith("14 cases · 3 behavior changes")
    assert "invalid cases dropped" not in text


def test_text_usage_line_comes_last() -> None:
    lines = results_text(sample_report()).splitlines()

    assert lines[0].startswith("14 cases")
    assert lines[-1].startswith("LLM: 3 calls")


@pytest.mark.parametrize(
    ("count", "text"),
    [(0, "0 LLM calls"), (1, "1 LLM call"), (2, "2 LLM calls")],
)
def test_counted_uses_the_singular_only_for_one(count: int, text: str) -> None:
    assert counted(count, "LLM call") == text


def test_usage_line_says_call_for_a_single_call() -> None:
    report = dataclasses.replace(
        sample_report(), usage=ReportUsage(1, 1000, 600, 400, 0.0004)
    )

    assert results_text(report).splitlines()[-1].startswith("LLM: 1 call · 1000")


def test_usage_line_says_cost_unknown_without_a_price() -> None:
    report = dataclasses.replace(
        sample_report(), usage=ReportUsage(2, 1000, 600, None, None)
    )

    last = results_text(report).splitlines()[-1]

    assert last.endswith("600 output tokens · cost unknown")


ESCAPE = "\x1b]0;owned\x07\x1b[2J"


def hostile_report() -> Report:
    # Audit 35a, finding 8: LLM text and user reprs reached the terminal as is.
    report = sample_report()
    finding = dataclasses.replace(
        report.findings[1],
        case=Case((f"'{ESCAPE}'",)),
        after=Outcome("return", "app.Weird", f"<Weird {ESCAPE}>"),
        reason=f"looks fine{ESCAPE}\nreally",
    )
    return dataclasses.replace(
        report,
        findings=(finding,),
        skipped=(SkippedItem("app/x.py::g", f"llm request rejected: {ESCAPE}"),),
    )


def test_text_report_has_no_terminal_control_characters() -> None:
    text = results_text(hostile_report(), color=True)

    controls = {c for c in text if ord(c) < 0x20 and c != "\n"}
    assert controls == {"\x1b"}  # only didibreak's own color codes
    assert "\x1b]" not in text and "\x07" not in text and "\x1b[2J" not in text
    assert r"\x1b]0;owned\x07\x1b[2J" in text
    assert "looks fine" in text and "really" in text


def test_json_report_keeps_the_original_text() -> None:
    data = report_json(hostile_report())

    assert data["findings"][0]["reason"] == f"looks fine{ESCAPE}\nreally"
    assert data["findings"][0]["after"]["repr"] == f"<Weird {ESCAPE}>"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("plain é 字", "plain é 字"),
        ("a\tb\r\nc", "a b  c"),
        ("\x00\x1f\x7f\x9b", r"\x00\x1f\x7f\x9b"),
    ],
)
def test_printable_replaces_only_control_characters(text: str, shown: str) -> None:
    assert printable(text) == shown
