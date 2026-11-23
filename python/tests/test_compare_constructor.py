"""A constructor that fails in one version only is a finding (task 38)."""

from didibreak.arguments import format_case_call
from didibreak.compare import (
    constructor_findings,
    constructor_name,
    finding_id,
    is_constructor_finding,
)
from didibreak.harness import Case, Outcome

METHOD = "app/bank.py::Account.deposit"
STATE = {"type": "state", "items": [[{"type": "str", "value": "balance"}, {}]]}


def built(stable: bool = True) -> Outcome:
    instance = Outcome(
        "return",
        "app.bank.Account",
        "<Account>",
        state=STATE,
        state_repr="{'balance': -1}",
    )
    return Outcome(
        "return",
        "builtins.NoneType",
        "None",
        {"type": "none"},
        stable=stable,
        state=STATE,
        state_repr="{'balance': 0}",
        construction=instance,
    )


def failed() -> Outcome:
    return Outcome(
        "exception",
        "builtins.ValueError",
        "ValueError('negative balance')",
        message="negative balance",
        construction_failed=True,
    )


CASE = Case(("1",), {}, "negative start", ("-1",), {})


def test_a_constructor_that_now_rejects_an_argument_is_a_finding() -> None:
    (finding,) = constructor_findings(METHOD, [CASE], [built()], [failed()])

    assert finding.function == "app/bank.py::Account.__init__"
    assert finding.case == Case((), {}, "negative start", ("-1",), {})
    assert finding.before is not None
    assert finding.before.state_repr == "{'balance': -1}"  # right after __init__
    assert finding.after.type_name == "builtins.ValueError"
    assert finding.confidence == "high"
    assert is_constructor_finding(finding)


def test_a_constructor_that_now_accepts_an_argument_is_a_finding() -> None:
    (finding,) = constructor_findings(METHOD, [CASE], [failed()], [built()])

    assert finding.before is not None
    assert finding.before.kind == "exception"
    assert finding.after.type_name == "app.bank.Account"


def test_the_finding_is_the_same_for_every_method_of_the_class() -> None:
    other = Case(("'x'",), {}, "", ("-1",), {})

    (first,) = constructor_findings(METHOD, [CASE], [built()], [failed()])
    (second,) = constructor_findings(
        "app/bank.py::Account.rename", [other], [built()], [failed()]
    )

    assert first.id == second.id == finding_id(first.function, first.case)


def test_construction_in_both_or_neither_version_is_no_finding() -> None:
    both = constructor_findings(METHOD, [CASE], [failed()], [failed()])
    neither = constructor_findings(METHOD, [CASE], [built()], [built()])

    assert both == neither == ()


def test_an_unstable_side_is_no_finding() -> None:
    assert constructor_findings(METHOD, [CASE], [built(False)], [failed()]) == ()


def test_a_timeout_while_building_is_no_constructor_finding() -> None:
    timeout = Outcome("timeout", "", "timed out after 5s")

    assert constructor_findings(METHOD, [CASE], [timeout], [failed()]) == ()


def test_the_constructor_call_is_shown_without_a_method() -> None:
    assert constructor_name("a.py::Box.size") == "a.py::Box.__init__"
    assert format_case_call("a.py::Box.__init__", (), {}, ("1",), {}) == "a.py::Box(1)"
    assert (
        format_case_call("a.py::Box.size", (), {}, ("1",), {}) == "a.py::Box(1).size()"
    )


def test_a_function_named_init_is_not_a_constructor_finding() -> None:
    (finding,) = constructor_findings(METHOD, [CASE], [built()], [failed()])
    function_case = Case(("1",))

    assert not is_constructor_finding(
        type(finding)(
            "x", "a.py::helper.__init__", function_case, None, built(), "high"
        )
    )
