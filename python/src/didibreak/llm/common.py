"""Shared parts of the LLM clients: data types, errors, retries, JSON checks.

The API key is only ever placed in request headers. Every error message is
built from the HTTP status and the provider's error text with the key
removed (redact), so it cannot reach logs, reports or the cache.
"""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

# Seconds; reasoning models can take a while before the first byte.
REQUEST_TIMEOUT = 120.0
CONNECT_TIMEOUT = 10.0
MAX_RETRIES = 2
BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
# Rate limits, timeouts, conflicts and server errors are worth retrying;
# 529 is Anthropic's "overloaded".
RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
ERROR_TEXT_LIMIT = 300
SHORT_MESSAGE_LIMIT = 120


@dataclass(frozen=True)
class Message:
    """One chat message: ``system``, ``user`` or ``assistant``."""

    role: str
    content: str


@dataclass(frozen=True)
class TokenUsage:
    """Tokens of one or more LLM calls.

    Attributes:
        input_tokens: All input tokens, cached ones included.
        output_tokens: All output tokens, reasoning tokens included (they are
            billed as output).
        reasoning_tokens: Reasoning tokens inside output_tokens, when the
            provider reports them; None otherwise.
        cached_input_tokens: Input tokens read from the provider's cache.
        calls: Number of requests the usage covers.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int | None = None
    cached_input_tokens: int = 0
    calls: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """Sum two usages; reasoning stays None only if both are None."""
        reasoning = (
            None
            if self.reasoning_tokens is None and other.reasoning_tokens is None
            else (self.reasoning_tokens or 0) + (other.reasoning_tokens or 0)
        )
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=reasoning,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            calls=self.calls + other.calls,
        )


@dataclass(frozen=True)
class LLMReply:
    """A schema-valid JSON object and the usage of the calls that produced it."""

    data: dict[str, Any]
    usage: TokenUsage
    model: str


@dataclass(frozen=True)
class RawReply:
    """One provider response before JSON parsing.

    Attributes:
        text: The model's text, or None when there is none.
        usage: Token usage of this call.
        model: Model name the provider reports.
        problem: Why the text cannot be used (refusal, cut off), or None.
    """

    text: str | None
    usage: TokenUsage
    model: str
    problem: str | None = None


@dataclass(frozen=True)
class ClientSettings:
    """What a client needs to call one provider.

    Attributes:
        model: Model name.
        base_url: API base URL, e.g. ``https://api.openai.com/v1``.
        api_key: The key, or None for local servers; never shown in repr.
        api_key_variable: Name of the variable holding the key, for messages.
        temperature: Sent only when set (owner decision 2026-11-06).
        timeout: Read timeout per request, seconds.
        max_retries: Retries after the first attempt for retryable failures.
    """

    model: str
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    api_key_variable: str | None = None
    temperature: float | None = None
    timeout: float = REQUEST_TIMEOUT
    max_retries: int = MAX_RETRIES


class LLMError(Exception):
    """An LLM call failed; the message is user-facing and contains no key."""


class LLMAuthError(LLMError):
    """The provider rejected the API key (HTTP 401/403): stop the run."""


class LLMModelError(LLMError):
    """Unknown model or wrong base URL (HTTP 404): stop the run."""


class LLMRequestError(LLMError):
    """The provider rejected the request (other HTTP 4xx).

    Attributes:
        provider_message: Short single-line summary such as ``HTTP 400:
            temperature is not supported``, for a skip reason.
    """

    def __init__(self, message: str, provider_message: str = "") -> None:
        """Keep a short form of the provider's message next to the full one."""
        super().__init__(message)
        self.provider_message = provider_message


class LLMUnavailableError(LLMError):
    """Rate limit, server error or network failure after all retries."""


class LLMInvalidResponseError(LLMError):
    """The reply is not schema-valid JSON, also after one retry.

    Attributes:
        usage: Tokens spent on the failed attempts, for cost accounting.
    """

    def __init__(self, message: str, usage: TokenUsage | None = None) -> None:
        """Keep the usage of the failed calls next to the message."""
        super().__init__(message)
        self.usage = usage or TokenUsage()


class LLMClient(Protocol):
    """The one call both clients offer."""

    def complete_json(
        self,
        messages: Sequence[Message],
        schema: Mapping[str, Any],
        schema_name: str,
    ) -> LLMReply:
        """Ask for a JSON object matching ``schema``; see the implementations."""
        ...


def redact(text: str, secret: str | None) -> str:
    """Remove a secret from text."""
    return text.replace(secret, "[redacted]") if secret else text


def schema_errors(
    instance: object, schema: Mapping[str, Any], path: str = "$"
) -> list[str]:
    """Check an instance against the JSON Schema subset didibreak uses.

    Supported keywords: ``type`` (object, array, string, integer, number,
    boolean, null), ``properties``, ``required``, ``additionalProperties:
    false``, ``items`` and ``enum``.

    Args:
        instance: Parsed JSON.
        schema: The schema.
        path: Location for messages, ``$`` for the root.

    Returns:
        Problems found, empty when the instance is valid.
    """
    expected = schema.get("type")
    if expected is not None and not _has_type(instance, expected):
        return [f"{path}: expected {expected}"]
    if "enum" in schema and instance not in schema["enum"]:
        return [f"{path}: {instance!r} is not one of {schema['enum']}"]
    errors: list[str] = []
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        errors += [
            f"{path}: missing {name!r}"
            for name in schema.get("required", [])
            if name not in instance
        ]
        if schema.get("additionalProperties") is False:
            errors += [
                f"{path}: unexpected {k!r}" for k in instance if k not in properties
            ]
        for name, value in instance.items():
            if name in properties:
                errors += schema_errors(value, properties[name], f"{path}.{name}")
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors += schema_errors(item, schema["items"], f"{path}[{index}]")
    return errors


def _has_type(instance: object, expected: str) -> bool:
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, int | float) and not isinstance(instance, bool)
    types: dict[str, type | tuple[type, ...]] = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "null": type(None),
    }
    return isinstance(instance, types.get(expected, object))


def api_error_text(response: httpx.Response) -> str:
    """The provider's error message from a JSON error body, or the raw text."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:ERROR_TEXT_LIMIT]
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    text = message if isinstance(message, str) else json.dumps(body)
    return text[:ERROR_TEXT_LIMIT]


def _status_error(response: httpx.Response, settings: ClientSettings) -> LLMError:
    status = response.status_code
    detail = f"HTTP {status}: {api_error_text(response)}"
    if status in (401, 403):
        variable = settings.api_key_variable or "the API key variable"
        message = f"the LLM provider rejected the API key ({detail}); check {variable}"
        return LLMAuthError(redact(message, settings.api_key))
    if status == 404:
        message = (
            f"model {settings.model!r} was not found at {settings.base_url} "
            f"({detail}); check model and base_url"
        )
        return LLMModelError(redact(message, settings.api_key))
    message = f"the LLM provider rejected the request ({detail})"
    short = " ".join(redact(detail, settings.api_key).split())[:SHORT_MESSAGE_LIMIT]
    return LLMRequestError(redact(message, settings.api_key), short)


def _backoff_seconds(attempt: int, response: httpx.Response | None) -> float:
    retry_after = None if response is None else response.headers.get("retry-after")
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass  # an HTTP date: use the exponential backoff
    return float(min(BACKOFF_SECONDS * 2**attempt, MAX_BACKOFF_SECONDS))


def post_with_retries(
    http: httpx.Client,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    settings: ClientSettings,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """POST JSON, retrying rate limits, server and network errors with backoff.

    Args:
        http: The httpx client (its timeouts and TLS settings apply).
        url: Endpoint URL.
        headers: Request headers, including the key.
        payload: JSON body.
        settings: Model, key and retry settings.
        sleep: Wait function, replaced in tests.

    Returns:
        A successful (2xx) response.

    Raises:
        LLMAuthError: HTTP 401 or 403.
        LLMModelError: HTTP 404.
        LLMRequestError: Any other non-retryable 4xx.
        LLMUnavailableError: Still failing after ``settings.max_retries``
            retries.
    """
    failure = ""
    for attempt in range(settings.max_retries + 1):
        response: httpx.Response | None = None
        try:
            response = http.post(url, headers=dict(headers), json=payload)
        except httpx.TransportError as error:  # includes timeouts
            failure = f"{type(error).__name__}: {error}"
        else:
            if response.status_code < 400:
                return response
            if response.status_code not in RETRY_STATUSES:
                raise _status_error(response, settings)
            failure = f"HTTP {response.status_code}: {api_error_text(response)}"
        if attempt < settings.max_retries:
            sleep(_backoff_seconds(attempt, response))
    attempts = settings.max_retries + 1
    message = f"the LLM provider is unavailable after {attempts} attempts ({failure})"
    raise LLMUnavailableError(redact(message, settings.api_key))


def _parse(raw: RawReply, schema: Mapping[str, Any]) -> dict[str, Any] | str:
    """The parsed object, or a description of why the reply is unusable."""
    if raw.problem is not None:
        return raw.problem
    if raw.text is None:
        return "the reply has no text"
    try:
        data = json.loads(raw.text)
    except json.JSONDecodeError as error:
        return f"the reply is not JSON ({error.msg})"
    if not isinstance(data, dict):
        return "the reply is not a JSON object"
    errors = schema_errors(data, schema)
    if errors:
        return "the reply does not match the schema: " + "; ".join(errors[:3])
    return data


def complete_with_one_retry(
    attempt: Callable[[], RawReply], schema: Mapping[str, Any]
) -> LLMReply:
    """Call the provider, and once more if the reply is not schema-valid JSON.

    Spec: one retry on invalid JSON, then the caller skips the function.

    Args:
        attempt: Sends one request and returns the raw reply.
        schema: JSON schema the reply must match.

    Returns:
        The parsed object with the usage of every call made.

    Raises:
        LLMInvalidResponseError: Both replies were unusable; carries the
            usage of both calls.
    """
    total = TokenUsage()
    problem = ""
    for _ in range(2):
        raw = attempt()
        total += raw.usage
        parsed = _parse(raw, schema)
        if isinstance(parsed, dict):
            return LLMReply(parsed, total, raw.model)
        problem = parsed
    raise LLMInvalidResponseError(
        f"invalid LLM response after one retry: {problem}", total
    )


def http_client(
    settings: ClientSettings, transport: httpx.BaseTransport | None
) -> httpx.Client:
    """An httpx client with didibreak's timeouts and certificate checks.

    TLS verification uses httpx's default context, which loads certifi's CA
    bundle, so it works on macOS Pythons without a system CA bundle and
    without SSL_CERT_FILE.

    Args:
        settings: Supplies the read timeout.
        transport: Replacement transport for tests; None for real HTTP.

    Returns:
        A new client; close it after use.
    """
    timeout = httpx.Timeout(settings.timeout, connect=CONNECT_TIMEOUT)
    return httpx.Client(timeout=timeout, transport=transport)
