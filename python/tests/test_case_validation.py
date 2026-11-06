"""Accepting LLM-proposed cases: recorded replies, including malicious ones."""

import json
from pathlib import Path
from typing import Any

import pytest

from didibreak.cases import (
    CASES_SCHEMA,
    MAX_ARGUMENT_LENGTH,
    accept_cases,
    is_literal,
)
from didibreak.harness import Case
from didibreak.llm.common import schema_errors

RESPONSES = Path(__file__).parent / "llm_responses"
FUNCTION = "app/utils/phone.py::normalize_phone"


def recorded(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((RESPONSES / name).read_text(encoding="utf-8"))
    return data


def item(*args: str, rationale: str = "r", **kwargs: str) -> dict[str, Any]:
    pairs = [{"name": k, "value": v} for k, v in kwargs.items()]
    return {"args": list(args), "kwargs": pairs, "rationale": rationale}


def test_recorded_live_reply_is_schema_valid_and_accepted() -> None:
    # Reply recorded from the task 12 live OpenAI run (gpt-6-luna).
    data = recorded("openai_phone_cases.json")

    batch = accept_cases(data, 12, FUNCTION)

    assert schema_errors(data, CASES_SCHEMA) == []
    assert batch.invalid == 0
    assert [case.args for case in batch.cases] == [
        ("'995123'",),
        ("'+1 202-555-0123'",),
        ("'  +44 20 1234'",),
    ]
    assert batch.cases[0].rationale.startswith("The old version removes")


def test_every_malicious_case_is_rejected_and_counted() -> None:
    data = recorded("malicious_cases.json")

    batch = accept_cases(data, 50, FUNCTION)

    assert batch.cases == ()
    assert batch.invalid == len(data["cases"]) == 12


def test_code_inside_a_string_literal_is_only_data() -> None:
    batch = accept_cases({"cases": [item("'__import__(\"os\")'")]}, 5, FUNCTION)

    assert batch.cases == (Case(("'__import__(\"os\")'",), {}, "r"),)


def test_valid_and_invalid_cases_are_separated() -> None:
    data = {
        "cases": [
            item("1", strict="True"),
            item("os.getcwd()"),
            item("b'\\x00'", "-1.5", "None"),
            item("{'a': [1, (2, 3)], 'b': {4}}"),
        ]
    }

    batch = accept_cases(data, 10, FUNCTION)

    assert batch.invalid == 1
    assert batch.cases[0] == Case(("1",), {"strict": "True"}, "r")
    assert len(batch.cases) == 3


def test_duplicates_by_value_are_dropped_without_counting() -> None:
    data = {
        "cases": [
            item("'a'", x="1"),
            item('"a"', x="1", rationale="same value, other spelling"),
            item("'a'", x="2"),
        ]
    }

    batch = accept_cases(data, 10, FUNCTION)

    assert [case.kwargs for case in batch.cases] == [{"x": "1"}, {"x": "2"}]
    assert batch.invalid == 0


def test_at_most_the_requested_number_of_cases_is_kept() -> None:
    data = {"cases": [item(str(n)) for n in range(20)]}

    assert len(accept_cases(data, 12, FUNCTION).cases) == 12


@pytest.mark.parametrize(
    "text",
    [
        "'x' * 3",
        "frozenset()",
        "[" * 5000 + "]" * 5000,
        "'" + "a" * MAX_ARGUMENT_LENGTH + "'",
        "",
        3,
    ],
)
def test_non_literals_and_oversized_text_are_not_literals(text: object) -> None:
    assert not is_literal(text)


@pytest.mark.parametrize("text", ["-1", "-(1)", "1e309", "1+2j", "set()", "()"])
def test_literal_edge_cases_accepted_by_literal_eval(text: str) -> None:
    # All are plain data for ast.literal_eval (set() is special-cased).
    assert is_literal(text)


def test_malformed_items_are_invalid() -> None:
    data = {"cases": [None, {"args": "1"}, {"args": [], "kwargs": "x"}]}

    assert accept_cases(data, 5, FUNCTION).invalid == 3
