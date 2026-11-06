"""Make one real call through didibreak's OpenAI client and record the result.

For the owner, who holds the API key (task 13). From python/:

    uv run python scripts/llm_smoke.py [MODEL] [OUTPUT]

Reads OPENAI_API_KEY from the environment, asks for an intent-labelling
JSON object (the task 12 spike request) and writes the outcome to OUTPUT
(default /tmp/didibreak-client.txt): model, PASS or FAIL, token usage and
the reply. The key is never written or printed. No SSL_CERT_FILE is needed:
httpx brings its own CA bundle.
"""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

import httpx

from didibreak import __version__
from didibreak.config import Config, ConfigError
from didibreak.llm import client_settings, create_client
from didibreak.llm.common import LLMError, Message, redact

DEFAULT_OUTPUT = Path("/tmp/didibreak-client.txt")
SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "label": {
                        "type": "string",
                        "enum": ["expected", "unexpected", "unclear"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["finding_id", "label", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}
PROMPT = (
    "Intent: add international phone numbers. Label each finding expected, "
    "unexpected or unclear against the intent, with a one-sentence reason.\n"
    "Finding f1: normalize_phone('+1 202 555 0100') returned '+99512025550100' "
    "before and '+12025550100' after.\n"
    "Finding f2: normalize_phone('995 555 12 34 56') returned '+995555123456' "
    "before and '+995995555123456' after."
)


def run(
    output: Path,
    environment: Mapping[str, str],
    model: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Make the call and write the report; 0 PASS, 1 FAIL, 2 settings error."""
    config = Config(provider="openai", model=model)
    lines = [
        f"didibreak {__version__}, httpx {httpx.__version__}",
        f"SSL_CERT_FILE set: {'yes' if environment.get('SSL_CERT_FILE') else 'no'}",
    ]
    try:
        settings = client_settings(config, environment)
    except ConfigError as error:
        lines.append(f"FAIL (settings): {error}")
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 2
    lines.append(f"model requested: {settings.model}")
    try:
        with create_client(config, environment, transport) as client:
            reply = client.complete_json([Message("user", PROMPT)], SCHEMA, "labels")
    except LLMError as error:
        lines.append(
            f"FAIL ({type(error).__name__}): {redact(str(error), settings.api_key)}"
        )
        code = 1
    else:
        usage = reply.usage
        lines += [
            f"model reported: {reply.model}",
            "PASS: schema-valid JSON",
            f"usage: input_tokens={usage.input_tokens} "
            f"output_tokens={usage.output_tokens} "
            f"reasoning_tokens={usage.reasoning_tokens} "
            f"cached_input_tokens={usage.cached_input_tokens} calls={usage.calls}",
            json.dumps(reply.data, indent=2),
        ]
        code = 0
    output.write_text(
        redact("\n".join(lines) + "\n", settings.api_key), encoding="utf-8"
    )
    return code


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else None
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    code = run(output, os.environ, model)
    print(f"wrote {output} (exit {code})")
    sys.exit(code)
