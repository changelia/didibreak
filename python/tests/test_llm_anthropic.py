import json
from typing import Any

import httpx
import pytest

from didibreak.llm.anthropic import API_VERSION, MAX_TOKENS, AnthropicClient
from didibreak.llm.common import (
    ClientSettings,
    LLMAuthError,
    LLMInvalidResponseError,
    LLMUnavailableError,
    Message,
    TokenUsage,
)

KEY = "sk-ant-test-0123456789"
SCHEMA = {
    "type": "object",
    "properties": {"labels": {"type": "array", "items": {"type": "string"}}},
    "required": ["labels"],
    "additionalProperties": False,
}
MESSAGES = [Message("system", "You label findings."), Message("user", "label these")]


def message(text: str | None, stop_reason: str = "end_turn") -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "thinking", "thinking": ""}]
    if text is not None:
        content.append({"type": "text", "text": text})
    return {
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 40,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 5,
        },
    }


def make_client(
    replies: list[httpx.Response], **settings: Any
) -> tuple[AnthropicClient, list[dict[str, Any]]]:
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
        "model": "claude-haiku-5-5",
        "base_url": "https://api.anthropic.com",
        "api_key": KEY,
        "api_key_variable": "ANTHROPIC_API_KEY",
        **settings,
    }
    client = AnthropicClient(
        ClientSettings(**options), httpx.MockTransport(handler), sleep=lambda _: None
    )
    return client, sent


def test_request_uses_output_config_and_the_system_field() -> None:
    client, sent = make_client([httpx.Response(200, json=message('{"labels": []}'))])

    client.complete_json(MESSAGES, SCHEMA, "labels")

    request = sent[0]
    assert request["url"] == "https://api.anthropic.com/v1/messages"
    assert request["headers"]["x-api-key"] == KEY
    assert request["headers"]["anthropic-version"] == API_VERSION == "2026-10-21"
    assert request["body"] == {
        "model": "claude-haiku-5-5",
        "max_tokens": MAX_TOKENS,
        "system": "You label findings.",
        "messages": [{"role": "user", "content": "label these"}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }


def test_no_sampling_parameters_unless_temperature_is_configured() -> None:
    reply = message('{"labels": []}')
    unset, sent_unset = make_client([httpx.Response(200, json=reply)])
    set_, sent_set = make_client([httpx.Response(200, json=reply)], temperature=0.5)

    unset.complete_json(MESSAGES, SCHEMA, "labels")
    set_.complete_json(MESSAGES, SCHEMA, "labels")

    assert not {"temperature", "top_p", "top_k"} & set(sent_unset[0]["body"])
    assert sent_set[0]["body"]["temperature"] == 0.5


def test_text_block_is_parsed_and_cache_tokens_count_as_input() -> None:
    client, _ = make_client([httpx.Response(200, json=message('{"labels": ["a"]}'))])

    reply = client.complete_json(MESSAGES, SCHEMA, "labels")

    assert reply.data == {"labels": ["a"]}
    assert reply.model == "claude-haiku-5-5"
    assert reply.usage == TokenUsage(
        input_tokens=125,
        output_tokens=40,
        reasoning_tokens=None,
        cached_input_tokens=20,
        calls=1,
    )


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (message(None, stop_reason="refusal"), "refused"),
        (message('{"lab', stop_reason="max_tokens"), "cut off"),
        (message(None), "no text block"),
        (message('{"labels": "x"}'), "does not match the schema"),
    ],
)
def test_unusable_replies_are_retried_once_then_rejected(
    body: dict[str, Any], problem: str
) -> None:
    client, sent = make_client([httpx.Response(200, json=body)] * 2)

    with pytest.raises(LLMInvalidResponseError, match=problem):
        client.complete_json(MESSAGES, SCHEMA, "labels")

    assert len(sent) == 2


def test_bad_key_names_the_variable_without_showing_the_key() -> None:
    body = {
        "type": "error",
        "error": {
            "type": "authentication_error",
            "message": f"invalid x-api-key {KEY}",
        },
    }
    client, _ = make_client([httpx.Response(401, json=body)])

    with pytest.raises(LLMAuthError, match="check ANTHROPIC_API_KEY") as info:
        client.complete_json(MESSAGES, SCHEMA, "labels")

    assert KEY not in str(info.value)


def test_overloaded_is_retried_then_reported_unavailable() -> None:
    overloaded = httpx.Response(
        529,
        json={
            "type": "error",
            "error": {"type": "overloaded_error", "message": "Overloaded"},
        },
    )
    client, sent = make_client([overloaded] * 3)

    with pytest.raises(LLMUnavailableError, match="HTTP 529: Overloaded"):
        client.complete_json(MESSAGES, SCHEMA, "labels")

    assert len(sent) == 3
