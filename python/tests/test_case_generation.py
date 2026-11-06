"""pipeline.generate_cases with a fake LLM client (no network)."""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from didibreak.cases import load_template
from didibreak.functions import ChangedFunction
from didibreak.harness import Case
from didibreak.llm.common import (
    LLMAuthError,
    LLMInvalidResponseError,
    LLMReply,
    LLMUnavailableError,
    Message,
    TokenUsage,
)
from didibreak.pipeline import (
    INVALID_RESPONSE_REASON,
    NO_VALID_CASES_REASON,
    UNAVAILABLE_REASON,
    generate_cases,
)

USAGE = TokenUsage(100, 50, 20, 0, 1)


def function(name: str) -> ChangedFunction:
    return ChangedFunction(
        file="app/m.py",
        module="app.m",
        qualname=name,
        kind="changed",
        function_type="function",
        is_async=False,
        line=1,
        old_source=f"def {name}(x):\n    return x\n",
        new_source=f"def {name}(x):\n    return x + 1\n",
    )


class FakeClient:
    """Replies per function name; an Exception instance is raised instead."""

    def __init__(self, replies: Mapping[str, object]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete_json(
        self, messages: Sequence[Message], schema: Mapping[str, Any], schema_name: str
    ) -> LLMReply:
        prompt = messages[-1].content
        self.prompts.append(prompt)
        name = next(n for n in self.replies if f"::{n}\n" in prompt)
        reply = self.replies[name]
        if isinstance(reply, Exception):
            raise reply
        assert isinstance(reply, dict)
        return LLMReply(reply, USAGE, "fake-model")


def cases(*args: str) -> dict[str, Any]:
    return {"cases": [{"args": [a], "kwargs": [], "rationale": "r"} for a in args]}


def test_valid_cases_are_kept_and_usage_is_summed() -> None:
    client = FakeClient({"f": cases("1", "2"), "g": cases("'a'")})

    result = generate_cases(client, [function("f"), function("g")], 12, load_template())

    assert result.cases == {
        "app/m.py::f": (Case(("1",), {}, "r"), Case(("2",), {}, "r")),
        "app/m.py::g": (Case(("'a'",), {}, "r"),),
    }
    assert result.skipped == ()
    assert result.usage == TokenUsage(200, 100, 40, 0, 2)
    assert "Propose 12 cases." in client.prompts[0]


def test_invalid_cases_are_counted_and_a_function_without_valid_ones_is_skipped() -> (
    None
):
    client = FakeClient({"f": cases("1", "os.getcwd()"), "g": cases("eval('1')")})

    result = generate_cases(client, [function("f"), function("g")], 5, load_template())

    assert result.invalid_cases_dropped == 2
    assert list(result.cases) == ["app/m.py::f"]
    assert [(f.qualname, f.skip_reason) for f in result.skipped] == [
        ("g", NO_VALID_CASES_REASON)
    ]


def test_invalid_reply_skips_the_function_and_keeps_its_usage() -> None:
    error = LLMInvalidResponseError("bad", TokenUsage(10, 5, None, 0, 2))
    client = FakeClient({"f": error, "g": cases("1")})

    result = generate_cases(client, [function("f"), function("g")], 5, load_template())

    assert [(f.qualname, f.skip_reason) for f in result.skipped] == [
        ("f", INVALID_RESPONSE_REASON)
    ]
    assert result.usage.calls == 3


def test_unavailable_provider_skips_the_remaining_functions() -> None:
    client = FakeClient(
        {"f": cases("1"), "g": LLMUnavailableError("down"), "h": cases("2")}
    )
    functions = [function("f"), function("g"), function("h")]

    result = generate_cases(client, functions, 5, load_template())

    assert list(result.cases) == ["app/m.py::f"]
    assert [(f.qualname, f.skip_reason) for f in result.skipped] == [
        ("g", UNAVAILABLE_REASON),
        ("h", UNAVAILABLE_REASON),
    ]
    assert len(client.prompts) == 2  # h was never asked


def test_rejected_key_stops_generation() -> None:
    client = FakeClient({"f": LLMAuthError("rejected")})

    with pytest.raises(LLMAuthError):
        generate_cases(client, [function("f")], 5, load_template())
