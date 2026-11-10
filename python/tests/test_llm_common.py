import dataclasses
from collections.abc import Callable

import httpx
import pytest

from didibreak.llm.common import (
    MAX_BACKOFF_SECONDS,
    ClientSettings,
    LLMAuthError,
    LLMInvalidResponseError,
    LLMModelError,
    LLMRequestError,
    LLMUnavailableError,
    RawReply,
    TokenUsage,
    complete_with_one_retry,
    http_client,
    post_with_retries,
    schema_errors,
)

KEY = "sk-secret-key-0123456789"
SETTINGS = ClientSettings(
    model="m", base_url="https://llm.test/v1", api_key=KEY, api_key_variable="MY_KEY"
)
SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string", "enum": ["expected", "unexpected"]},
                    "score": {"type": "integer"},
                },
                "required": ["id", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def client(
    responses: list[httpx.Response | Exception],
) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return http_client(SETTINGS, httpx.MockTransport(handler)), seen


def post(
    responses: list[httpx.Response | Exception],
    sleep: Callable[[float], None] | None = None,
) -> httpx.Response:
    http, _ = client(responses)
    return post_with_retries(
        http, "https://llm.test/v1/x", {}, {}, SETTINGS, sleep or (lambda _: None)
    )


def test_valid_instance_has_no_errors() -> None:
    assert (
        schema_errors(
            {"labels": [{"id": "a", "label": "expected", "score": 1}]}, SCHEMA
        )
        == []
    )


@pytest.mark.parametrize(
    ("instance", "problem"),
    [
        ([], "$: expected object"),
        ({}, "missing 'labels'"),
        ({"labels": [{"id": "a"}]}, "missing 'label'"),
        ({"labels": [{"id": "a", "label": "maybe"}]}, "is not one of"),
        ({"labels": [{"id": "a", "label": "expected", "x": 1}]}, "unexpected 'x'"),
        (
            {"labels": [{"id": "a", "label": "expected", "score": True}]},
            "expected integer",
        ),
        (
            {"labels": [{"id": 1, "label": "expected"}]},
            "$.labels[0].id: expected string",
        ),
    ],
)
def test_invalid_instances_are_described(instance: object, problem: str) -> None:
    assert any(problem in error for error in schema_errors(instance, SCHEMA))


def test_usage_adds_up_and_keeps_unknown_reasoning_unknown() -> None:
    first = TokenUsage(10, 5, None, 0, 1)
    second = TokenUsage(3, 2, 1, 1, 1)

    assert first + TokenUsage(1, 1, None, 0, 1) == TokenUsage(11, 6, None, 0, 2)
    assert first + second == TokenUsage(13, 7, 1, 1, 2)


def test_success_is_returned_without_retry() -> None:
    assert post([httpx.Response(200, json={"ok": True})]).json() == {"ok": True}


def test_rate_limits_and_server_errors_are_retried_with_backoff() -> None:
    waits: list[float] = []
    responses: list[httpx.Response | Exception] = [
        httpx.Response(429, headers={"retry-after": "3"}),
        httpx.Response(503),
        httpx.Response(200, json={}),
    ]

    post(responses, waits.append)

    assert waits == [3.0, 2.0]  # Retry-After, then exponential (1 s * 2**1)


def test_retry_after_is_capped() -> None:
    waits: list[float] = []

    post(
        [httpx.Response(429, headers={"retry-after": "999"}), httpx.Response(200)],
        waits.append,
    )

    assert waits == [MAX_BACKOFF_SECONDS]


def test_network_errors_are_retried() -> None:
    error = httpx.ConnectError("connection refused")

    assert (
        post([error, httpx.ReadTimeout("slow"), httpx.Response(200)]).status_code == 200
    )


def test_unavailable_after_all_retries() -> None:
    responses: list[httpx.Response | Exception] = [httpx.Response(500)] * 3

    with pytest.raises(LLMUnavailableError, match="unavailable after 3 attempts"):
        post(responses)


@pytest.mark.parametrize(
    ("status", "error", "text"),
    [
        (401, LLMAuthError, "rejected the API key (HTTP 401); check that MY_KEY"),
        (403, LLMAuthError, "rejected the API key (HTTP 403); check that MY_KEY"),
        (404, LLMModelError, "model 'm' was not found at https://llm.test/v1"),
        (400, LLMRequestError, "rejected the request (HTTP 400: bad key)"),
    ],
)
def test_client_errors_stop_at_once_with_a_clear_message(
    status: int, error: type[Exception], text: str
) -> None:
    http, seen = client(
        [httpx.Response(status, json={"error": {"message": "bad key"}})]
    )

    with pytest.raises(error) as info:
        post_with_retries(http, "https://llm.test/v1/x", {}, {}, SETTINGS)

    assert text in str(info.value)
    assert len(seen) == 1


def test_rejected_request_keeps_a_short_single_line_provider_message() -> None:
    text = "temperature\nis not supported " + "x" * 300 + f" {KEY}"
    http, _ = client([httpx.Response(400, json={"error": {"message": text}})])

    with pytest.raises(LLMRequestError) as info:
        post_with_retries(http, "https://llm.test/v1/x", {}, {}, SETTINGS)

    short = info.value.provider_message
    assert short.startswith("HTTP 400: temperature is not supported")
    assert "\n" not in short
    assert len(short) <= 120
    assert KEY not in short


def test_the_key_never_appears_in_errors() -> None:
    echo = {"error": {"message": f"Incorrect API key provided: {KEY}"}}
    cases: list[list[httpx.Response | Exception]] = [
        [httpx.Response(400, json=echo)],
        [httpx.Response(500, json=echo)] * 3,
        [httpx.ConnectError(f"failed with {KEY}")] * 3,
    ]
    for responses in cases:
        with pytest.raises(Exception) as info:
            post(list(responses))
        assert KEY not in str(info.value)
        assert KEY not in repr(info.value)
        assert "[redacted]" in str(info.value)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_never_echo_the_provider_message(status: int) -> None:
    # OpenAI repeats a masked key: its first 8 and last 4 characters.
    masked = f"Incorrect API key provided: {KEY[:8]}{'*' * 12}{KEY[-4:]}."
    http, _ = client([httpx.Response(status, json={"error": {"message": masked}})])

    with pytest.raises(LLMAuthError) as info:
        post_with_retries(http, "https://llm.test/v1/x", {}, {}, SETTINGS)

    message = str(info.value)
    assert "Incorrect API key" not in message
    assert KEY[:8] not in message
    assert KEY[-4:] not in message
    assert "MY_KEY" in message


def test_auth_error_without_a_variable_names_the_setting() -> None:
    settings = dataclasses.replace(SETTINGS, api_key_variable=None)
    http, _ = client([httpx.Response(401, text="nope")])

    with pytest.raises(LLMAuthError, match="the variable named by api_key_env"):
        post_with_retries(http, "https://llm.test/v1/x", {}, {}, settings)


def test_settings_repr_hides_the_key() -> None:
    assert KEY not in repr(SETTINGS)


def test_default_tls_context_has_ca_certificates_without_ssl_cert_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # httpx loads certifi's bundle, so no system CA bundle or SSL_CERT_FILE is needed.
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)

    assert len(httpx.create_ssl_context().get_ca_certs()) > 0


def raw(text: str | None, problem: str | None = None) -> RawReply:
    return RawReply(text, TokenUsage(10, 4, None, 0, 1), "m", problem)


def test_valid_reply_is_parsed_on_the_first_call() -> None:
    replies = [raw('{"labels": []}')]

    reply = complete_with_one_retry(lambda: replies.pop(0), SCHEMA)

    assert reply.data == {"labels": []}
    assert reply.usage.calls == 1


def test_invalid_reply_is_retried_once_and_usage_is_summed() -> None:
    replies = [raw("not json"), raw('{"labels": []}')]

    reply = complete_with_one_retry(lambda: replies.pop(0), SCHEMA)

    assert reply.usage == TokenUsage(20, 8, None, 0, 2)


@pytest.mark.parametrize(
    ("first", "second", "problem"),
    [
        (raw("[]"), raw("[]"), "not a JSON object"),
        (raw("{}"), raw("{}"), "missing 'labels'"),
        (raw(None, "refused"), raw(None, "refused"), "refused"),
        (raw("x"), raw("{"), "not JSON"),
    ],
)
def test_second_invalid_reply_raises_with_the_usage(
    first: RawReply, second: RawReply, problem: str
) -> None:
    replies = [first, second]

    with pytest.raises(LLMInvalidResponseError, match=problem) as info:
        complete_with_one_retry(lambda: replies.pop(0), SCHEMA)

    assert info.value.usage.calls == 2


def test_tests_cannot_reach_the_real_network() -> None:
    with pytest.raises(RuntimeError, match="real network access in a test"):
        httpx.get("https://api.openai.com/v1/models")
