"""Client for OpenAI-compatible Chat Completions APIs (OpenAI, OpenRouter, Ollama).

Request and reply shapes were checked in the official docs and, for OpenAI,
with a live call on 2026-11-06 (task 12; see docs/providers-and-costs.md):
strict ``response_format`` JSON schema, text in
``choices[0].message.content``, refusals in ``message.refusal``, usage in
``prompt_tokens`` / ``completion_tokens`` with reasoning tokens included.
"""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

from didibreak import __version__
from didibreak.llm.common import (
    MAX_OUTPUT_TOKENS,
    ClientSettings,
    LLMReply,
    LLMRequestError,
    MayContinue,
    Message,
    RawReply,
    TokenUsage,
    complete_with_one_retry,
    http_client,
    post_with_retries,
)

# Words in a 400 error that mean the endpoint does not take a JSON schema;
# the owner-approved fallback (2026-11-06) is then JSON mode + a client check.
_SCHEMA_UNSUPPORTED_HINTS = ("response_format", "json_schema", "structured output")


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def parse_usage(body: Mapping[str, Any]) -> TokenUsage:
    """Token usage of one Chat Completions response."""
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return TokenUsage(calls=1)
    completion = usage.get("completion_tokens_details")
    prompt = usage.get("prompt_tokens_details")
    reasoning = (
        completion.get("reasoning_tokens") if isinstance(completion, dict) else None
    )
    return TokenUsage(
        input_tokens=_int(usage.get("prompt_tokens")),
        output_tokens=_int(usage.get("completion_tokens")),
        reasoning_tokens=reasoning if isinstance(reasoning, int) else None,
        cached_input_tokens=_int(prompt.get("cached_tokens"))
        if isinstance(prompt, dict)
        else 0,
        calls=1,
    )


def parse_reply(body: object, model: str) -> RawReply:
    """The text of the first choice, or why it cannot be used."""
    if not isinstance(body, dict):
        return RawReply(
            None, TokenUsage(calls=1), model, "the reply is not a JSON object"
        )
    usage = parse_usage(body)
    name = body.get("model")
    reported = name if isinstance(name, str) else model
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError):
        return RawReply(None, usage, reported, "the reply has no choices")
    if message.get("refusal"):
        return RawReply(
            None, usage, reported, f"the model refused: {str(message['refusal'])[:200]}"
        )
    if choice.get("finish_reason") in ("length", "content_filter"):
        reason = choice["finish_reason"]
        return RawReply(
            None, usage, reported, f"the reply was cut off (finish_reason {reason})"
        )
    content = message.get("content")
    return RawReply(content if isinstance(content, str) else None, usage, reported)


def request_payload(
    settings: ClientSettings,
    messages: Sequence[Message],
    schema: Mapping[str, Any],
    schema_name: str,
    json_mode: bool = False,
) -> dict[str, Any]:
    """The Chat Completions request body.

    Args:
        settings: Model, base URL and temperature.
        messages: Conversation to send.
        schema: JSON schema the reply must match.
        schema_name: Name for the schema (letters, digits, ``_``, ``-``).
        json_mode: Use the fallback: ``json_object`` with the schema in a
            system message instead of a strict JSON schema.

    Returns:
        The JSON body.
    """
    sent = list(messages)
    if json_mode:
        instruction = (
            "Reply with only a JSON object that matches this JSON Schema:\n"
            + json.dumps(schema)
        )
        sent.insert(0, Message("system", instruction))
        response_format: dict[str, Any] = {"type": "json_object"}
    else:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        }
    body: dict[str, Any] = {
        "model": settings.model,
        "messages": [{"role": m.role, "content": m.content} for m in sent],
        "response_format": response_format,
    }
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    if settings.output_limit_parameter is not None:
        body[settings.output_limit_parameter] = MAX_OUTPUT_TOKENS
    if urlparse(settings.base_url).hostname == "openrouter.ai":
        # Route only to endpoints that support structured outputs (OpenRouter docs).
        body["provider"] = {"require_parameters": True}
    return body


class OpenAICompatibleClient:
    """Chat Completions client; use as a context manager or call close()."""

    def __init__(
        self,
        settings: ClientSettings,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create the client.

        Args:
            settings: Model, base URL, key and limits.
            transport: Replacement transport for tests; None for real HTTP.
            sleep: Wait function for retry backoff, replaced in tests.
        """
        self.settings = settings
        self._http = http_client(settings, transport)
        self._sleep = sleep
        self._json_mode = False

    def __enter__(self) -> "OpenAICompatibleClient":
        """Return the client itself."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the HTTP connection pool."""
        self.close()

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self._http.close()

    def complete_json(
        self,
        messages: Sequence[Message],
        schema: Mapping[str, Any],
        schema_name: str,
        may_continue: MayContinue | None = None,
    ) -> LLMReply:
        """Ask for a JSON object matching ``schema``.

        Args:
            messages: Conversation to send.
            schema: JSON schema of the reply (strict: additionalProperties
                false and every property required).
            schema_name: Name for the schema.
            may_continue: Asked before a retry or the JSON-mode fallback
                request; None allows them.

        Returns:
            The schema-valid object and the usage of all calls made.

        Raises:
            LLMError: A subclass from llm.common describing the failure.
        """
        return complete_with_one_retry(
            lambda spent: self._attempt(
                messages, schema, schema_name, spent, may_continue
            ),
            schema,
            may_continue,
        )

    def _post(self, payload: Mapping[str, Any]) -> httpx.Response:
        headers = {"user-agent": f"didibreak/{__version__}"}
        if self.settings.api_key:
            headers["authorization"] = f"Bearer {self.settings.api_key}"
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        return post_with_retries(
            self._http, url, headers, payload, self.settings, self._sleep
        )

    def _attempt(
        self,
        messages: Sequence[Message],
        schema: Mapping[str, Any],
        schema_name: str,
        spent: TokenUsage,
        may_continue: MayContinue | None,
    ) -> RawReply:
        payload = request_payload(
            self.settings, messages, schema, schema_name, self._json_mode
        )
        try:
            response = self._post(payload)
        except LLMRequestError as error:
            text = str(error).lower()
            if self._json_mode or not any(h in text for h in _SCHEMA_UNSUPPORTED_HINTS):
                raise
            if may_continue is not None and not may_continue(spent):
                raise  # the run's limit does not allow the fallback request
            self._json_mode = True  # stays on for this client's later calls
            payload = request_payload(
                self.settings, messages, schema, schema_name, True
            )
            response = self._post(payload)
        try:
            body = response.json()
        except ValueError:
            body = None
        return parse_reply(body, self.settings.model)
