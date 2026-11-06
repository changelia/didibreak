"""Spike: Anthropic Messages API structured output (run by the owner).

Usage, from python/:
    ANTHROPIC_API_KEY=... uv run --with certifi python spike/spike_anthropic.py [MODEL]

Request shape verified from the official docs on 2026-11-06: header
anthropic-version 2026-10-21, output_config {"format": {"type":
"json_schema", "schema": ...}}, JSON text in the first "text" content block,
stop_reason "refusal" / "max_tokens" checked first, usage.input_tokens /
usage.output_tokens. No temperature: on 2026-10-21 any temperature, top_p
or top_k is a 400 error.
"""

import sys
from collections.abc import Mapping
from typing import Any

from spike_common import REQUESTS, api_key, post_json, print_failure, report

URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"


def messages_payload(
    model: str, prompt: str, schema: Mapping[str, Any]
) -> dict[str, Any]:
    """Messages request with JSON-schema structured output."""
    return {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }


def reply_text(body: Any) -> str | None:
    """The JSON text, or None when the reply was refused or cut off."""
    if not isinstance(body, dict):
        return None
    if body.get("stop_reason") in ("refusal", "max_tokens"):
        print(f"stop_reason: {body['stop_reason']}")
        return None
    for block in body.get("content", []):
        if block.get("type") == "text":
            text = block.get("text")
            return text if isinstance(text, str) else None
    return None


def main(model: str) -> int:
    """Send both requests; 0 if both replies are schema-valid."""
    key = api_key("ANTHROPIC_API_KEY")
    headers = {"x-api-key": key, "anthropic-version": API_VERSION}
    passed = True
    for title, _, schema, prompt in REQUESTS:
        reply = post_json(URL, headers, messages_payload(model, prompt, schema))
        if reply.status != 200:
            print_failure(title, reply.status, reply.body, key)
            passed = False
            continue
        passed &= report(title, reply_text(reply.body), schema, reply.body.get("usage"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-5-5"))
