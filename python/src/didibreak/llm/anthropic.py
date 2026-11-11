"""Client for the Anthropic Messages API.

Shapes checked in the official docs on 2026-11-06 (task 12) but
**unverified by a live call** (no key was available; required before
release, task 23): header ``anthropic-version: 2026-10-21``,
``output_config.format`` with a JSON schema, JSON text in the first
``text`` content block, ``stop_reason`` ``refusal`` / ``max_tokens`` checked
first, usage ``input_tokens`` / ``output_tokens`` plus cache fields. API
version 2026-10-21 rejects any ``temperature``, so it is sent only when the
user configures one.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

from didibreak import __version__
from didibreak.llm.common import (
    MAX_OUTPUT_TOKENS,
    ClientSettings,
    LLMReply,
    MayContinue,
    Message,
    RawReply,
    TokenUsage,
    complete_with_one_retry,
    http_client,
    post_with_retries,
)

API_VERSION = "2026-10-21"
DEFAULT_BASE_URL = "https://api.anthropic.com"
# Room for adaptive thinking plus a JSON reply; non-streaming requests stay
# well under the HTTP timeouts at this size. The Messages API requires it.
MAX_TOKENS = MAX_OUTPUT_TOKENS


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def parse_usage(body: Mapping[str, Any]) -> TokenUsage:
    """Token usage of one Messages response; cache tokens count as input."""
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return TokenUsage(calls=1)
    cache_read = _int(usage.get("cache_read_input_tokens"))
    cache_write = _int(usage.get("cache_creation_input_tokens"))
    return TokenUsage(
        input_tokens=_int(usage.get("input_tokens")) + cache_read + cache_write,
        output_tokens=_int(usage.get("output_tokens")),
        reasoning_tokens=None,  # not reported separately by the Messages API
        cached_input_tokens=cache_read,
        calls=1,
    )


def parse_reply(body: object, model: str) -> RawReply:
    """The JSON text of a Messages response, or why it cannot be used."""
    if not isinstance(body, dict):
        return RawReply(
            None, TokenUsage(calls=1), model, "the reply is not a JSON object"
        )
    usage = parse_usage(body)
    name = body.get("model")
    reported = name if isinstance(name, str) else model
    stop_reason = body.get("stop_reason")
    if stop_reason == "refusal":
        return RawReply(
            None, usage, reported, "the model refused (stop_reason refusal)"
        )
    if stop_reason == "max_tokens":
        return RawReply(
            None, usage, reported, "the reply was cut off (stop_reason max_tokens)"
        )
    for block in body.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            return RawReply(text if isinstance(text, str) else None, usage, reported)
    return RawReply(None, usage, reported, "the reply has no text block")


def request_payload(
    settings: ClientSettings, messages: Sequence[Message], schema: Mapping[str, Any]
) -> dict[str, Any]:
    """The Messages request body; system messages go to the ``system`` field."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    body: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    if system:
        body["system"] = system
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    return body


class AnthropicClient:
    """Messages API client; use as a context manager or call close()."""

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

    def __enter__(self) -> "AnthropicClient":
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
            messages: Conversation to send; ``system`` messages become the
                system prompt.
            schema: JSON schema of the reply (objects need
                additionalProperties false).
            schema_name: Unused by this API; kept for the shared signature.
            may_continue: Asked before a retry; None allows it.

        Returns:
            The schema-valid object and the usage of all calls made.

        Raises:
            LLMError: A subclass from llm.common describing the failure.
        """
        return complete_with_one_retry(
            lambda _spent: self._attempt(messages, schema), schema, may_continue
        )

    def _attempt(
        self, messages: Sequence[Message], schema: Mapping[str, Any]
    ) -> RawReply:
        headers = {
            "user-agent": f"didibreak/{__version__}",
            "anthropic-version": API_VERSION,
        }
        if self.settings.api_key:
            headers["x-api-key"] = self.settings.api_key
        url = self.settings.base_url.rstrip("/") + "/v1/messages"
        payload = request_payload(self.settings, messages, schema)
        response = post_with_retries(
            self._http, url, headers, payload, self.settings, self._sleep
        )
        try:
            body = response.json()
        except ValueError:
            body = None
        return parse_reply(body, self.settings.model)
