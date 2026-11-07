"""Text report: snapshot, label order, colors and the usage line (task 18)."""

from report_samples import check_snapshot, sample_report

from didibreak.report.text import results_text


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
