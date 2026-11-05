import pytest

from didibreak._harness_child import normalize
from didibreak.compare import (
    HIGH_CONFIDENCE,
    LOW_CONFIDENCE,
    NEW_FUNCTION_LABEL,
    Comparison,
    compare_cases,
    difference,
    finding_id,
)
from didibreak.harness import PROCESS_EXITED_TYPE, Case, Outcome

FUNCTION = "app/m.py::f"
CASE = Case(("1",))


def returned(value: object, stable: bool = True) -> Outcome:
    kind = type(value)
    return Outcome(
        "return",
        f"{kind.__module__}.{kind.__qualname__}",
        repr(value),
        value=normalize(value),
        stable=stable,
    )


def raised(type_name: str, message: str = "") -> Outcome:
    return Outcome("exception", type_name, f"E({message!r})", message=message)


def unrepresentable(type_name: str) -> Outcome:
    return Outcome("return", type_name, "<object at 0x1>")


TIMEOUT = Outcome("timeout", "", "<timed out after 10 s>")


def one_case(before: Outcome | None, after: Outcome) -> Comparison:
    return compare_cases(
        FUNCTION, [CASE], None if before is None else [before], [after]
    )


def test_flaky_case_is_dropped_and_counted() -> None:
    for before, after in [
        (returned("a", stable=False), returned("b")),
        (returned("a"), returned("b", stable=False)),
    ]:
        result = one_case(before, after)

        assert result.findings == ()
        assert result.flaky_dropped == 1


def test_floats_within_tolerance_are_not_a_finding() -> None:
    assert difference(returned(0.1 + 0.2), returned(0.3)) is None


def test_floats_outside_tolerance_are_a_high_confidence_finding() -> None:
    assert difference(returned(11.86), returned(11.9)) == HIGH_CONFIDENCE


def test_same_exception_type_is_not_a_finding_even_with_another_message() -> None:
    before = raised("builtins.ValueError", "invalid literal")
    after = raised("builtins.ValueError", "bad age")

    assert difference(before, after) is None


def test_different_exception_type_is_a_finding() -> None:
    before = raised("builtins.ValueError")
    after = raised("builtins.IndexError")

    assert difference(before, after) == HIGH_CONFIDENCE


def test_raise_versus_return_is_a_finding_both_ways() -> None:
    assert difference(raised("builtins.ValueError"), returned(1)) == HIGH_CONFIDENCE
    assert difference(returned(1), raised("builtins.ValueError")) == HIGH_CONFIDENCE


def test_timeout_on_one_side_is_a_finding() -> None:
    assert one_case(TIMEOUT, returned(1)).findings[0].after == returned(1)
    assert one_case(returned(1), TIMEOUT).findings[0].after == TIMEOUT


def test_timeout_on_both_sides_is_dropped() -> None:
    result = one_case(TIMEOUT, TIMEOUT)

    assert result.findings == ()
    assert result.timeouts_dropped == 1


def test_unrepresentable_values_are_compared_by_type_with_low_confidence() -> None:
    same_type = (unrepresentable("app.Point"), unrepresentable("app.Point"))
    other_type = (unrepresentable("app.Point"), unrepresentable("app.Vector"))

    assert difference(*same_type) is None
    assert difference(*other_type) == LOW_CONFIDENCE


def test_value_on_one_side_only_is_compared_by_type() -> None:
    assert difference(returned([1]), unrepresentable("builtins.list")) is None
    assert difference(returned(1), unrepresentable("app.Number")) == LOW_CONFIDENCE


def test_new_function_reports_exceptions_and_timeouts_only() -> None:
    cases = [Case(("''",)), Case(("'ada lovelace'",)), Case(("0",)), Case(("1",))]
    after = [
        raised("builtins.ValueError"),
        returned("AL"),
        TIMEOUT,
        raised(PROCESS_EXITED_TYPE),
    ]

    result = compare_cases(FUNCTION, cases, None, after)

    assert [f.case for f in result.findings] == [cases[0], cases[2], cases[3]]
    assert {f.label for f in result.findings} == {NEW_FUNCTION_LABEL}
    assert all(f.before is None for f in result.findings)


def test_new_function_explicitly_raised_types_are_not_findings() -> None:
    cases = [Case(("'x'",)), Case(("''",)), Case(("0",)), Case(("1",))]
    after = [
        raised("builtins.ValueError"),
        raised("app.m.OutOfRange"),
        raised("builtins.IndexError"),
        raised(PROCESS_EXITED_TYPE),
    ]
    explicit = {"builtins.ValueError", "app.m.OutOfRange", PROCESS_EXITED_TYPE}

    result = compare_cases(FUNCTION, cases, None, after, explicit_raises=explicit)

    # IndexError is not raised explicitly; a crash is always reported.
    assert [f.case for f in result.findings] == [cases[2], cases[3]]


def test_explicit_raises_do_not_hide_timeouts_or_changed_function_findings() -> None:
    explicit = {"builtins.ValueError"}

    new = compare_cases(FUNCTION, [CASE], None, [TIMEOUT], explicit_raises=explicit)
    changed = compare_cases(
        FUNCTION,
        [CASE],
        [returned(1)],
        [raised("builtins.ValueError")],
        explicit_raises=explicit,
    )

    assert len(new.findings) == len(changed.findings) == 1


def test_new_function_flaky_case_is_dropped() -> None:
    unstable = Outcome("exception", "builtins.KeyError", "KeyError()", stable=False)

    result = compare_cases(FUNCTION, [CASE], None, [unstable])

    assert (result.findings, result.flaky_dropped) == ((), 1)


def test_finding_carries_id_outcomes_and_no_label_yet() -> None:
    before, after = returned("+995555123456"), returned("+995995555123456")

    (finding,) = one_case(before, after).findings

    assert finding.id == finding_id(FUNCTION, CASE)
    assert (finding.function, finding.case) == (FUNCTION, CASE)
    assert (finding.before, finding.after) == (before, after)
    assert finding.confidence == HIGH_CONFIDENCE
    assert finding.label is None


def test_counts_cover_every_case() -> None:
    cases = [Case((str(n),)) for n in range(4)]
    before = [returned(1), returned(1, stable=False), TIMEOUT, returned(2)]
    after = [returned(1), returned(1), TIMEOUT, returned(3)]

    result = compare_cases(FUNCTION, cases, before, after)

    assert result.cases_run == 4
    assert (result.flaky_dropped, result.timeouts_dropped) == (1, 1)
    assert [f.case for f in result.findings] == [cases[3]]


def test_outcome_lists_must_match_the_cases() -> None:
    with pytest.raises(ValueError):
        compare_cases(FUNCTION, [CASE, CASE], [returned(1)], [returned(1)])
