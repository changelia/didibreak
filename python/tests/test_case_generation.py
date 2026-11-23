"""pipeline.generate_cases with a fake LLM client (no network)."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import pytest

from didibreak.cases import (
    REFINEMENT_PROMPT_FILE,
    CaseRun,
    build_messages,
    load_template,
)
from didibreak.functions import ChangedFunction
from didibreak.harness import Case, Outcome
from didibreak.llm.common import (
    ClientSettings,
    LLMAuthError,
    LLMInvalidResponseError,
    LLMModelError,
    LLMReply,
    LLMRequestError,
    LLMUnavailableError,
    Message,
    TokenUsage,
)
from didibreak.llm.openai_compat import OpenAICompatibleClient
from didibreak.llm.pricing import Price, cost_usd
from didibreak.pipeline import (
    COST_LIMIT_REASON,
    INVALID_RESPONSE_REASON,
    NO_NEW_CASES_REASON,
    NO_VALID_CASES_REASON,
    OUTPUT_TOKENS_PER_CASE,
    TOKEN_LIMIT_REASON,
    UNAVAILABLE_REASON,
    Budget,
    case_reply_tokens,
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
        self.caps: list[int] = []

    def complete_json(
        self,
        messages: Sequence[Message],
        schema: Mapping[str, Any],
        schema_name: str,
        may_continue: Any = None,
        max_output_tokens: int = 16000,
    ) -> LLMReply:
        prompt = messages[-1].content
        self.prompts.append(prompt)
        self.caps.append(max_output_tokens)
        name = next(n for n in self.replies if f"::{n}\n" in prompt)
        reply = self.replies[name]
        if isinstance(reply, list):  # one reply per request, in order
            reply = reply.pop(0)
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

    result = generate_cases(
        client, functions, 5, load_template(), budget=Budget(PRICE, limit, 5)
    )

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

    result = generate_cases(
        client, [function("f")], 5, load_template(), budget=Budget(PRICE, 1e-9, 5)
    )

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

    result = generate_cases(
        client, functions, 5, template, budget=Budget(PRICE, limit, 5)
    )

    assert len(result.cases) == 3


def test_without_a_price_there_is_no_limit_and_no_cost() -> None:
    client = FakeClient({"f": cases("1")})

    result = generate_cases(
        client, [function("f")], 5, load_template(), budget=Budget(None, 0.0, 5)
    )

    assert list(result.cases) == ["app/m.py::f"]
    assert result.cost_usd is None


def test_failed_attempts_are_counted_in_the_cost() -> None:
    error = LLMInvalidResponseError("bad", TokenUsage(1000, 1000, None, 0, 2))
    client = FakeClient({"f": error})

    result = generate_cases(
        client, [function("f")], 5, load_template(), budget=Budget(PRICE, 10.0, 5)
    )

    assert result.cost_usd == pytest.approx((1000 * 1.0 + 1000 * 10.0) / 1_000_000)


def run_of(case: Case, value: str) -> CaseRun:
    same = Outcome("return", "builtins.str", value)
    return CaseRun(case, same, same)


def test_refinement_sends_previous_results_and_drops_tried_cases() -> None:
    tried = [run_of(Case(("1",), {}, "r"), "'x'")]
    client = FakeClient({"f": cases("1", "2")})  # "1" was already tried

    result = generate_cases(
        client,
        [function("f")],
        5,
        load_template(REFINEMENT_PROMPT_FILE),
        previous={"app/m.py::f": tried},
    )

    assert "- f(1) -> old: 'x'; new: 'x'" in client.prompts[0]
    assert result.cases == {"app/m.py::f": (Case(("2",), {}, "r"),)}
    assert result.invalid_cases_dropped == 0


def test_refinement_with_only_tried_cases_is_reported() -> None:
    tried = [run_of(Case(("1",), {}, "r"), "'x'")]
    client = FakeClient({"f": cases("1")})

    result = generate_cases(
        client,
        [function("f")],
        5,
        load_template(REFINEMENT_PROMPT_FILE),
        previous={"app/m.py::f": tried},
    )

    assert [f.skip_reason for f in result.skipped] == [NO_NEW_CASES_REASON]


def test_a_shared_budget_limits_all_rounds_and_rounds_report_their_own_usage() -> None:
    heavy = TokenUsage(2000, 5000, 4000, 0, 1)
    client = FakeClient({"f": cases("1"), "g": cases("2")}, usage=heavy)
    budget = Budget(PRICE, cost_usd(heavy, PRICE) * 1.5, 5)

    first = generate_cases(client, [function("f")], 5, load_template(), budget=budget)
    second = generate_cases(
        client,
        [function("g")],
        5,
        load_template(REFINEMENT_PROMPT_FILE),
        budget=budget,
        previous={"app/m.py::g": []},
    )

    assert first.usage == heavy
    assert first.cost_usd == pytest.approx(cost_usd(heavy, PRICE))
    assert [f.skip_reason for f in second.skipped] == [COST_LIMIT_REASON]
    assert second.usage.calls == 0
    assert second.cost_usd == 0.0
    assert budget.usage == heavy


def _first_request_tokens(count: int) -> int:
    estimate = estimate_call(
        build_messages(function("f"), count, load_template()),
        count,
        OUTPUT_TOKENS_PER_CASE,
    )
    return estimate.input_tokens + estimate.output_tokens


@pytest.mark.parametrize("price", [PRICE, None], ids=["priced", "unpriced"])
def test_token_limit_skips_the_rest_with_or_without_a_price(
    price: Price | None,
) -> None:
    heavy = TokenUsage(3000, 2000, None, 0, 1)
    client = FakeClient({"f": cases("1"), "g": cases("2")}, usage=heavy)
    limit = 5000 + _first_request_tokens(5) - 1  # f fits, g does not
    budget = Budget(price, None, 5, max_tokens=limit)

    result = generate_cases(
        client, [function("f"), function("g")], 5, load_template(), budget=budget
    )

    assert list(result.cases) == ["app/m.py::f"]
    assert [f.skip_reason for f in result.skipped] == [TOKEN_LIMIT_REASON]
    assert result.usage.calls == 1


def test_a_request_that_fits_the_token_limit_exactly_is_sent() -> None:
    client = FakeClient({"f": cases("1")})
    budget = Budget(None, None, 5, max_tokens=_first_request_tokens(5))

    result = generate_cases(client, [function("f")], 5, load_template(), budget=budget)

    assert result.skipped == ()
    assert len(client.prompts) == 1


def test_a_too_small_token_limit_sends_nothing() -> None:
    client = FakeClient({"f": cases("1")})
    budget = Budget(None, None, 5, max_tokens=_first_request_tokens(5) - 1)

    result = generate_cases(client, [function("f")], 5, load_template(), budget=budget)

    assert client.prompts == []
    assert [f.skip_reason for f in result.skipped] == [TOKEN_LIMIT_REASON]


def test_cost_limit_wins_when_both_limits_are_exceeded() -> None:
    budget = Budget(PRICE, 1e-12, 5, max_tokens=1)

    messages = build_messages(function("f"), 5, load_template())

    assert budget.refusal(messages) == COST_LIMIT_REASON


def test_audit_case_stays_within_max_tokens_plus_one_reply() -> None:
    # Audit 35a, finding 4: every reply is cut off. Before 0.1.4 the client
    # retried without asking the budget (123,000 tokens for a 20,000 limit)
    # and sent no output cap.
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        body = {
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 16000},
        }
        return httpx.Response(200, json=body)

    settings = ClientSettings(
        model="gpt-6-luna",
        base_url="https://api.openai.com/v1",
        output_limit_parameter="max_completion_tokens",
    )
    client = OpenAICompatibleClient(
        settings, httpx.MockTransport(handler), sleep=lambda _: None
    )
    budget = Budget(None, None, 12, max_tokens=20_000)

    result = generate_cases(
        client, [function("f"), function("g")], 12, load_template(), budget=budget
    )

    # The server ignores the cap (task 38: 8,400 for 12 cases) and replies
    # with 16,000 tokens; the retry still does not fit.
    assert [body["max_completion_tokens"] for body in sent] == [8400]
    assert [(f.qualname, f.skip_reason) for f in result.skipped] == [
        ("f", INVALID_RESPONSE_REASON),
        ("g", TOKEN_LIMIT_REASON),
    ]
    one_reply = 1500 + 16000
    used = budget.usage.input_tokens + budget.usage.output_tokens
    assert used == one_reply  # the retry was not sent
    assert used <= 20_000 + one_reply


def _large_reply_client(usage: object) -> tuple[OpenAICompatibleClient, list[bytes]]:
    """A server whose every reply is about 47,000 characters of valid cases."""
    sent: list[bytes] = []
    reply_cases = [
        {"args": [str(number)], "kwargs": [], "rationale": "r" * 3900}
        for number in range(12)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        choice = {"message": {"content": json.dumps({"cases": reply_cases})}}
        body: dict[str, Any] = {"choices": [choice]}
        if usage is not None:
            body["usage"] = usage
        return httpx.Response(200, json=body)

    settings = ClientSettings(model="m", base_url="https://llm.test/v1")
    client = OpenAICompatibleClient(
        settings, httpx.MockTransport(handler), sleep=lambda _: None
    )
    return client, sent


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"prompt_tokens": 0, "completion_tokens": 0},
        {"prompt_tokens": -100000, "completion_tokens": 8000},
        {"prompt_tokens": "many", "completion_tokens": None},
    ],
    ids=["missing", "zeros", "negative", "not numbers"],
)
def test_token_limit_stops_a_server_that_reports_no_usage(usage: object) -> None:
    # Pre-launch review, finding 4: such replies counted as 0 tokens, so all
    # ten requests were sent under a limit that stops an honest server.
    client, sent = _large_reply_client(usage)
    functions = [function(f"f{number}") for number in range(10)]
    budget = Budget(None, None, 12, max_tokens=20_000)

    result = generate_cases(client, functions, 12, load_template(), budget=budget)

    assert len(sent) == 1
    assert [f.skip_reason for f in result.skipped] == [TOKEN_LIMIT_REASON] * 9
    assert result.usage.estimated_calls == 1
    counted = result.usage.input_tokens + result.usage.output_tokens
    assert counted >= 47_000 // 3  # the reply alone is about 15,800 tokens


def test_cost_limit_stops_a_server_that_reports_no_usage() -> None:
    client, sent = _large_reply_client(None)
    functions = [function(f"f{number}") for number in range(10)]
    budget = Budget(PRICE, 0.05, 12)

    result = generate_cases(client, functions, 12, load_template(), budget=budget)

    assert 0 < len(sent) < 10
    assert result.skipped[-1].skip_reason == COST_LIMIT_REASON
    assert budget.cost > 0


def test_reported_usage_is_not_replaced_by_an_estimate() -> None:
    client, sent = _large_reply_client(
        {"prompt_tokens": 600, "completion_tokens": 8000}
    )
    functions = [function(f"f{number}") for number in range(10)]
    budget = Budget(None, None, 12, max_tokens=20_000)

    result = generate_cases(client, functions, 12, load_template(), budget=budget)

    assert len(sent) == 2
    assert result.usage == TokenUsage(1200, 16000, None, 0, 2)
    assert result.usage.estimated_calls == 0


@pytest.mark.parametrize(
    ("count", "cap"), [(1, 4000), (5, 4000), (12, 8400), (22, 15400), (50, 16000)]
)
def test_the_reply_cap_follows_the_number_of_cases(count: int, cap: int) -> None:
    assert case_reply_tokens(count) == cap


def test_case_requests_ask_for_the_reply_cap() -> None:
    client = FakeClient({"f": cases("1")})

    generate_cases(client, [function("f")], 12, load_template())

    assert client.caps == [8400]


def test_the_reply_cap_stays_within_max_tokens() -> None:
    messages = build_messages(function("f"), 12, load_template())
    prompt = estimate_call(messages, 0, 0).input_tokens
    budget = Budget(None, None, 12, max_tokens=prompt + 5000)

    assert budget.reply_cap(messages) == 5000
    budget.add(TokenUsage(1000, 1000, None, 0, 1))
    assert budget.reply_cap(messages) == 3000


def test_the_reply_cap_stays_within_max_cost() -> None:
    messages = build_messages(function("f"), 12, load_template())
    prompt = estimate_call(messages, 0, 0)
    # $10 per million output tokens: 2,000 tokens cost $0.02.
    budget = Budget(PRICE, cost_usd(prompt, PRICE) + 0.02, 12)

    assert budget.reply_cap(messages) in (1999, 2000)  # rounded down
    assert Budget(PRICE, None, 12).reply_cap(messages) == 8400


def test_a_labelling_request_keeps_the_large_cap_within_the_limits() -> None:
    messages = build_messages(function("f"), 12, load_template())

    assert Budget(None, None, 12).reply_cap(messages, 16000) == 16000
