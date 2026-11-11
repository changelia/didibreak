import json
from typing import Any

import httpx
import pytest

from didibreak.llm.common import (
    ClientSettings,
    LLMInvalidResponseError,
    LLMRequestError,
    Message,
    TokenUsage,
)
from didibreak.llm.openai_compat import OpenAICompatibleClient

KEY = "sk-test-openai-0123456789"
SCHEMA = {
    "type": "object",
    "properties": {"labels": {"type": "array", "items": {"type": "string"}}},
    "required": ["labels"],
    "additionalProperties": False,
}
MESSAGES = [Message("user", "label these")]
# Usage shape from the task 12 live call (gpt-6-luna).
LIVE_USAGE = {
    "prompt_tokens": 213,
    "completion_tokens": 537,
    "total_tokens": 750,
    "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
    "completion_tokens_details": {"reasoning_tokens": 399},
}


def completion(content: str | None, **message: Any) -> dict[str, Any]:
    finish = message.pop("finish_reason", "stop")
    return {
        "model": "gpt-6-luna",
        "choices": [
            {
                "message": {"role": "assistant", "content": content, **message},
                "finish_reason": finish,
            }
        ],
        "usage": LIVE_USAGE,
    }


def make_client(
    replies: list[httpx.Response], **settings: Any
) -> tuple[OpenAICompatibleClient, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": json.loads(request.content),
            }
        )
        return replies.pop(0)

    options = {
        "model": "gpt-6-luna",
        "base_url": "https://api.openai.com/v1",
        "api_key": KEY,
        **settings,
    }
    client = OpenAICompatibleClient(
        ClientSettings(**options), httpx.MockTransport(handler), sleep=lambda _: None
    )
    return client, sent


def test_request_asks_for_a_strict_json_schema_with_the_key_in_the_header() -> None:
    client, sent = make_client([httpx.Response(200, json=completion('{"labels": []}'))])

    client.complete_json(MESSAGES, SCHEMA, "labels")

    request = sent[0]
    assert request["url"] == "https://api.openai.com/v1/chat/completions"
    assert request["headers"]["authorization"] == f"Bearer {KEY}"
    assert request["body"] == {
        "model": "gpt-6-luna",
        "messages": [{"role": "user", "content": "label these"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "labels", "strict": True, "schema": SCHEMA},
        },
    }


def test_temperature_is_sent_only_when_configured() -> None:
    reply = completion('{"labels": []}')
    unset, sent_unset = make_client([httpx.Response(200, json=reply)])
    set_, sent_set = make_client([httpx.Response(200, json=reply)], temperature=0.2)

    unset.complete_json(MESSAGES, SCHEMA, "labels")
    set_.complete_json(MESSAGES, SCHEMA, "labels")

    assert "temperature" not in sent_unset[0]["body"]
    assert sent_set[0]["body"]["temperature"] == 0.2


def test_local_servers_get_no_authorization_header() -> None:
    client, sent = make_client(
        [httpx.Response(200, json=completion('{"labels": []}'))],
        api_key=None,
        base_url="http://localhost:11434/v1",
    )

    client.complete_json(MESSAGES, SCHEMA, "labels")

    assert "authorization" not in sent[0]["headers"]
    assert sent[0]["url"] == "http://localhost:11434/v1/chat/completions"


def test_openrouter_requests_require_structured_output_support() -> None:
    reply = completion('{"labels": []}')
    router, sent_router = make_client(
        [httpx.Response(200, json=reply)], base_url="https://openrouter.ai/api/v1"
    )
    openai, sent_openai = make_client([httpx.Response(200, json=reply)])

    router.complete_json(MESSAGES, SCHEMA, "labels")
    openai.complete_json(MESSAGES, SCHEMA, "labels")

    assert sent_router[0]["body"]["provider"] == {"require_parameters": True}
    assert "provider" not in sent_openai[0]["body"]


def test_reply_and_usage_with_reasoning_tokens_are_returned() -> None:
    client, _ = make_client([httpx.Response(200, json=completion('{"labels": ["a"]}'))])

    reply = client.complete_json(MESSAGES, SCHEMA, "labels")

    assert reply.data == {"labels": ["a"]}
    assert reply.model == "gpt-6-luna"
    assert reply.usage == TokenUsage(
        input_tokens=213,
        output_tokens=537,
        reasoning_tokens=399,
        cached_input_tokens=0,
        calls=1,
    )


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (completion(None, refusal="I can't help with that."), "the model refused"),
        (completion('{"lab', finish_reason="length"), "cut off"),
        (completion("not json"), "not JSON"),
        (completion('{"labels": [1]}'), "does not match the schema"),
        ({"choices": []}, "no choices"),
    ],
)
def test_unusable_replies_are_retried_once_then_rejected(
    body: dict[str, Any], problem: str
) -> None:
    client, sent = make_client([httpx.Response(200, json=body)] * 2)

    with pytest.raises(LLMInvalidResponseError, match=problem) as info:
        client.complete_json(MESSAGES, SCHEMA, "labels")

    assert len(sent) == 2
    assert info.value.usage.calls == 2


def test_endpoint_without_json_schema_falls_back_to_json_mode() -> None:
    unsupported = httpx.Response(
        400,
        json={"error": {"message": "response_format json_schema is not supported"}},
    )
    ok = httpx.Response(200, json=completion('{"labels": []}'))
    client, sent = make_client(
        [unsupported, ok, httpx.Response(200, json=completion('{"labels": []}'))]
    )

    first = client.complete_json(MESSAGES, SCHEMA, "labels")
    client.complete_json(MESSAGES, SCHEMA, "labels")

    assert first.data == {"labels": []}
    fallback = sent[1]["body"]
    assert fallback["response_format"] == {"type": "json_object"}
    assert fallback["messages"][0]["role"] == "system"
    assert "JSON Schema" in fallback["messages"][0]["content"]
    assert json.dumps(SCHEMA) in fallback["messages"][0]["content"]
    assert sent[2]["body"]["response_format"] == {"type": "json_object"}  # stays on


def test_other_bad_requests_do_not_trigger_the_fallback() -> None:
    bad = httpx.Response(400, json={"error": {"message": "messages must not be empty"}})
    client, sent = make_client([bad])

    with pytest.raises(LLMRequestError, match="messages must not be empty"):
        client.complete_json(MESSAGES, SCHEMA, "labels")

    assert len(sent) == 1


def test_non_json_success_body_is_an_invalid_reply() -> None:
    client, _ = make_client([httpx.Response(200, text="<html>")] * 2)

    with pytest.raises(LLMInvalidResponseError, match="not a JSON object"):
        client.complete_json(MESSAGES, SCHEMA, "labels")


def test_client_closes_as_a_context_manager() -> None:
    client, _ = make_client([])

    with client as same:
        assert same is client

    assert client._http.is_closed


def test_json_mode_fallback_is_not_sent_when_the_run_limit_refuses() -> None:
    # Audit 35a, finding 4: the fallback request skipped the budget check.
    unsupported = httpx.Response(
        400,
        json={"error": {"message": "response_format json_schema is not supported"}},
    )
    client, sent = make_client([unsupported])

    with pytest.raises(LLMRequestError, match="json_schema is not supported"):
        client.complete_json(MESSAGES, SCHEMA, "labels", lambda _spent: False)

    assert len(sent) == 1


@pytest.mark.parametrize(
    ("parameter", "expected"),
    [("max_completion_tokens", 16000), ("max_tokens", 16000), (None, None)],
)
def test_output_cap_uses_only_the_configured_field(
    parameter: str | None, expected: int | None
) -> None:
    reply = httpx.Response(200, json=completion('{"labels": []}'))
    client, sent = make_client([reply], output_limit_parameter=parameter)

    client.complete_json(MESSAGES, SCHEMA, "labels")

    body = sent[0]["body"]
    fields = {"max_completion_tokens", "max_tokens"} & set(body)
    assert fields == (set() if parameter is None else {parameter})
    assert body.get(parameter or "", None) == expected
