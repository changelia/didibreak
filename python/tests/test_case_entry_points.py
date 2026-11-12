"""The same case inputs through every entry point (audit 35a, finding 11).

Cases reach the harness from four places: LLM replies (cases.accept_cases),
the case cache, the hidden --cases-file option and the harness's own check.
Each row says which entry points accept the input.
"""

from collections.abc import Mapping

import pytest

from didibreak import cache, cases, harness, pipeline
from didibreak.compare import Finding
from didibreak.harness import Case, Outcome
from didibreak.report import pytest_writer
from didibreak.report.pytest_writer import finding_call
from didibreak.report.text import _finding_lines

LONG = "'" + "a" * 3000 + "'"


def accepted_by_llm_path(args: list[str], kwargs: Mapping[str, str]) -> bool:
    pairs = [{"name": name, "value": value} for name, value in kwargs.items()]
    item = {"args": args, "kwargs": pairs, "rationale": "r"}
    return cases.accept_cases({"cases": [item]}, 5, "a.py::f").cases != ()


def accepted_by_cache(args: list[str], kwargs: Mapping[str, str]) -> bool:
    item = {"args": args, "kwargs": dict(kwargs), "rationale": "r"}
    return cache._case_from_json(item) is not None


def accepted_by_cases_file(args: list[str], kwargs: Mapping[str, str]) -> bool:
    item = {"function": "a.py::f", "args": args, "kwargs": dict(kwargs)}
    try:
        pipeline._case(item, 1)
    except ValueError:
        return False
    return True


def accepted_by_harness(args: list[str], kwargs: Mapping[str, str]) -> bool:
    try:
        harness._check_literals([Case(tuple(args), dict(kwargs))])
    except ValueError:
        return False
    return True


ENTRY_POINTS = {
    "llm": accepted_by_llm_path,
    "cache": accepted_by_cache,
    "cases_file": accepted_by_cases_file,
    "harness": accepted_by_harness,
}
EVERYWHERE = dict.fromkeys(ENTRY_POINTS, True)
NOWHERE = dict.fromkeys(ENTRY_POINTS, False)


@pytest.mark.parametrize(
    ("args", "kwargs", "expected"),
    [
        (["1", "'a'", "[1, (2, 3)]", "{'k': b'v'}", "None"], {"x": "1.5"}, EVERYWHERE),
        (["-1", "1e309", "{1, 2}", "1j", "...", "b''"], {}, EVERYWHERE),
        (["frozenset()"], {}, NOWHERE),
        (["__import__('os')"], {}, NOWHERE),
        (["print(1)"], {}, NOWHERE),
        (["x"], {}, NOWHERE),
        ([], {"x": "open('f')"}, NOWHERE),
        # Before task 35c the entry points disagreed on these three:
        ([LONG], {}, {**NOWHERE, "cases_file": True, "harness": True}),
        ([], {"class": "1"}, {**EVERYWHERE, "llm": False}),
        ([], {"not a name": "1"}, {**NOWHERE, "cases_file": True, "harness": True}),
    ],
    ids=[
        "literals",
        "more-literals",
        "frozenset-call",
        "call",
        "builtin-call",
        "name",
        "keyword-call",
        "too-long",
        "keyword-name",
        "not-identifier",
    ],
)
def test_every_entry_point_accepts_the_same_inputs(
    args: list[str], kwargs: dict[str, str], expected: dict[str, bool]
) -> None:
    results = {name: check(args, kwargs) for name, check in ENTRY_POINTS.items()}

    assert results == expected


def finding(function: str, case: Case) -> Finding:
    outcome = Outcome("return", "builtins.int", "1", {"type": "int", "value": 1})
    return Finding("0" * 12, function, case, outcome, outcome, "high")


CASE = Case(("1", "'a b'"), {"k": "[2]", "z": "None"})


def test_every_formatter_writes_the_arguments_the_same_way() -> None:
    assert cases.describe_call("C.m", CASE) == "m(1, 'a b', k=[2], z=None)"
    assert finding_call(finding("a.py::f", CASE)) == "a.py::f(1, 'a b', k=[2], z=None)"
    assert (
        pytest_writer._call("C", finding("a.py::C.m", CASE), "C.m")
        == "C.m(1, 'a b', k=[2], z=None)"
    )
    line = _finding_lines(finding("a.py::f", CASE), color=False)[0]
    assert line.endswith("a.py::f(1, 'a b', k=[2], z=None)")


def test_formatters_handle_no_arguments() -> None:
    empty = Case(())

    assert cases.describe_call("f", empty) == "f()"
    assert finding_call(finding("a.py::f", empty)) == "a.py::f()"
