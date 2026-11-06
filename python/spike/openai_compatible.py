"""Chat Completions spike shared by the OpenAI, OpenRouter and Ollama scripts.

Request shape verified from the official docs on 2026-11-06 (links in
docs/providers-and-costs.md): response_format {"type": "json_schema",
"json_schema": {"name", "strict": true, "schema"}}, reply text in
choices[0].message.content, refusals in choices[0].message.refusal, usage
in usage.prompt_tokens / usage.completion_tokens.
"""

from collections.abc import Mapping
from typing import Any

from spike_common import REQUESTS, post_json, print_failure, redact, report


def chat_payload(
    model: str, prompt: str, name: str, schema: Mapping[str, Any]
) -> dict[str, Any]:
    """Chat Completions request asking for strict JSON-schema output."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        },
    }


def reply_text(body: Any) -> str | None:
    """The JSON text of the first choice, or None (refusal, error, empty)."""
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return None
    if message.get("refusal"):
        print(f"refusal: {message['refusal']}")
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def run(
    base_url: str,
    model: str,
    key: str,
    extra: Mapping[str, Any] | None = None,
    probe_temperature: bool = True,
) -> int:
    """Send both requests (and a temperature probe); 0 if all are valid."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"authorization": f"Bearer {key}"} if key else {}
    passed = True
    for title, name, schema, prompt in REQUESTS:
        payload = {**chat_payload(model, prompt, name, schema), **(extra or {})}
        reply = post_json(url, headers, payload)
        if reply.status != 200:
            print_failure(title, reply.status, reply.body, key)
            passed = False
            continue
        usage = reply.body.get("usage") if isinstance(reply.body, dict) else None
        passed &= report(title, reply_text(reply.body), schema, usage)
    if probe_temperature:
        # Detailed Design section 5 asks for temperature 0.2 / 0; check it is accepted.
        _, name, schema, prompt = REQUESTS[1]
        payload = {
            **chat_payload(model, prompt, name, schema),
            "temperature": 0,
            **(extra or {}),
        }
        reply = post_json(url, headers, payload)
        detail = (
            "" if reply.status == 200 else f": {redact(str(reply.body), key)[:300]}"
        )
        print(f"--- temperature 0 probe: HTTP {reply.status}{detail}")
    return 0 if passed else 1
