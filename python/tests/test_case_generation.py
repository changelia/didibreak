"""pipeline.generate_cases with a fake LLM client (no network)."""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from didibreak.cases import build_messages, load_template
from didibreak.functions import ChangedFunction
from didibreak.harness import Case
from didibreak.llm.common import (
    LLMAuthError,
    LLMInvalidResponseError,
    LLMModelError,
    LLMReply,
    LLMRequestError,
    LLMUnavailableError,
    Message,
    TokenUsage,
)
from didibreak.llm.pricing import Price, cost_usd
from didibreak.pipeline import (
    COST_LIMIT_REASON,
    INVALID_RESPONSE_REASON,
    NO_VALID_CASES_REASON,
    OUTPUT_TOKENS_PER_CASE,
    UNAVAILABLE_REASON,
    estimate_call,
    estimate_generation,
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

    def __init__(
        self, replies: Mapping[str, object], usage: TokenUsage = USAGE
    ) -> None:
        self.replies = replies
        self.usage = usage
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
        return LLMReply(reply, self.usage, "fake-model")


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


def test_other_rejected_requests_skip_only_that_function() -> None:
    rejected = LLMRequestError("full message", "HTTP 400: temperature is not supported")
    client = FakeClient({"f": rejected, "g": cases("1")})

    result = generate_cases(client, [function("f"), function("g")], 5, load_template())

    assert list(result.cases) == ["app/m.py::g"]
    assert [(f.qualname, f.skip_reason) for f in result.skipped] == [
        ("f", "llm request rejected: HTTP 400: temperature is not supported")
    ]


@pytest.mark.parametrize("error", [LLMAuthError("rejected"), LLMModelError("no model")])
def test_auth_and_model_errors_stop_generation(error: Exception) -> None:
    client = FakeClient({"f": error})

    with pytest.raises(type(error)):
        generate_cases(client, [function("f")], 5, load_template())


def test_rejected_key_stops_generation() -> None:
    client = FakeClient({"f": LLMAuthError("rejected")})

    with pytest.raises(LLMAuthError):
        generate_cases(client, [function("f")], 5, load_template())


PRICE = Price(input=1.0, output=10.0)  # USD per million tokens, easy numbers


def test_estimate_uses_prompt_size_and_the_per_case_default() -> None:
    template = load_template()
    functions = [function("f"), function("g")]

    estimate = estimate_generation(functions, 12, template, PRICE)

    one = estimate_call(build_messages(function("f"), 12, template), 12, 180)
    assert one.output_tokens == OUTPUT_TOKENS_PER_CASE * 12 == 2160
    assert estimate.calls == 2
    assert estimate.usage.output_tokens == 2 * 2160
    assert estimate.usage.input_tokens >= 2 * one.input_tokens - 2
    assert estimate.cost_usd == pytest.approx(cost_usd(estimate.usage, PRICE))


def test_estimate_without_a_price_has_tokens_only() -> None:
    estimate = estimate_generation([function("f")], 3, load_template(), None)

    assert estimate.cost_usd is None
    assert estimate.usage.input_tokens > 0


def test_cost_limit_stops_before_the_request_that_would_exceed_it() -> None:
    heavy = TokenUsage(2000, 5000, 4000, 0, 1)  # 1,000 output tokens per case
    replies = {"f": cases("1"), "g": cases("2"), "h": cases("3")}
    client = FakeClient(replies, usage=heavy)
    limit = cost_usd(heavy, PRICE) * 1.5  # room for one such request
    functions = [function("f"), function("g"), function("h")]

    result = generate_cases(client, functions, 5, load_template(), PRICE, limit)

    assert list(result.cases) == ["app/m.py::f"]
    assert [(f.qualname, f.skip_reason) for f in result.skipped] == [
        ("g", COST_LIMIT_REASON),
        ("h", COST_LIMIT_REASON),
    ]
    assert len(client.prompts) == 1
    assert result.cost_usd == pytest.approx(cost_usd(heavy, PRICE))
    assert result.cost_usd is not None and result.cost_usd <= limit


def test_limit_too_low_for_the_first_request_sends_nothing() -> None:
    client = FakeClient({"f": cases("1")})

    result = generate_cases(client, [function("f")], 5, load_template(), PRICE, 1e-9)

    assert client.prompts == []
    assert [f.skip_reason for f in result.skipped] == [COST_LIMIT_REASON]
    assert result.cost_usd == 0.0


def test_observed_completion_tokens_replace_the_default_estimate() -> None:
    # USAGE reports 50 output tokens for 5 requested cases: 10 per case,
    # far below the 180 default, so all three requests fit.
    client = FakeClient({"f": cases("1"), "g": cases("2"), "h": cases("3")})
    template = load_template()
    first = estimate_call(build_messages(function("f"), 5, template), 5, 180)
    limit = cost_usd(first, PRICE) * 1.5
    functions = [function("f"), function("g"), function("h")]

    result = generate_cases(client, functions, 5, template, PRICE, limit)

    assert len(result.cases) == 3


def test_without_a_price_there_is_no_limit_and_no_cost() -> None:
    client = FakeClient({"f": cases("1")})

    result = generate_cases(client, [function("f")], 5, load_template(), None, 0.0)

    assert list(result.cases) == ["app/m.py::f"]
    assert result.cost_usd is None


def test_failed_attempts_are_counted_in_the_cost() -> None:
    error = LLMInvalidResponseError("bad", TokenUsage(1000, 1000, None, 0, 2))
    client = FakeClient({"f": error})

    result = generate_cases(client, [function("f")], 5, load_template(), PRICE, 10.0)

    assert result.cost_usd == pytest.approx((1000 * 1.0 + 1000 * 10.0) / 1_000_000)
