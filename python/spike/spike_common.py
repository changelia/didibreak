"""Shared code for the task 12 provider spike scripts (throwaway, not shipped).

Each script sends the two structured-output requests didibreak needs, case
generation (Detailed Design section 5.1) and intent labelling (5.3), and
checks the reply against the JSON schema. Standard library only, so the
scripts run before the LLM clients exist. API keys are read from the
environment, sent only in request headers and removed from anything printed.
"""

import importlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Strict structured output (OpenAI strict mode, Anthropic output_config.format)
# needs additionalProperties: false on every object, so keyword arguments are
# a list of name/value pairs instead of a map (decision pending, task 12).
CASES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "args": {"type": "array", "items": {"type": "string"}},
                    "kwargs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["args", "kwargs", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cases"],
    "additionalProperties": False,
}

LABELS_SCHEMA: dict[str, Any] = {
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

CASES_PROMPT = (
    "Propose 3 input cases that could reveal a behavior difference between "
    "these two versions of a Python function. Every argument must be a "
    "Python literal written as a string.\n\nOld:\n"
    "def normalize_phone(raw):\n"
    "    digits = ''.join(c for c in raw if c.isdigit())\n"
    "    if digits.startswith('995'):\n"
    "        digits = digits[3:]\n"
    "    return '+995' + digits\n\nNew:\n"
    "def normalize_phone(raw):\n"
    "    digits = ''.join(c for c in raw if c.isdigit())\n"
    "    if raw.strip().startswith('+'):\n"
    "        return '+' + digits\n"
    "    return '+995' + digits\n"
)

LABELS_PROMPT = (
    "Intent: add international phone numbers. Label each finding expected, "
    "unexpected or unclear against the intent, with a one-sentence reason.\n"
    "Finding f1: normalize_phone('+1 202 555 0100') returned '+99512025550100' "
    "before and '+12025550100' after.\n"
    "Finding f2: normalize_phone('995 555 12 34 56') returned '+995555123456' "
    "before and '+995995555123456' after."
)

REQUESTS = (
    ("case generation", "didibreak_cases", CASES_SCHEMA, CASES_PROMPT),
    ("intent labelling", "didibreak_labels", LABELS_SCHEMA, LABELS_PROMPT),
)


def schema_errors(
    instance: object, schema: Mapping[str, Any], path: str = "$"
) -> list[str]:
    """Check an instance against the small JSON Schema subset used above."""
    expected = schema.get("type")
    checks = {
        "object": dict,
        "array": list,
        "string": str,
    }
    if expected in checks and not isinstance(instance, checks[expected]):
        return [f"{path}: expected {expected}"]
    if "enum" in schema and instance not in schema["enum"]:
        return [f"{path}: {instance!r} not in {schema['enum']}"]
    errors: list[str] = []
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}: missing {name!r}")
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: extra {k!r}" for k in instance if k not in properties]
        for name, value in instance.items():
            if name in properties:
                errors += schema_errors(value, properties[name], f"{path}.{name}")
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors += schema_errors(item, schema["items"], f"{path}[{index}]")
    return errors


def api_key(variable: str) -> str:
    """Read an API key from the environment; exit 2 if it is not set."""
    key = os.environ.get(variable, "")
    if not key:
        print(f"{variable} is not set; nothing was sent.", file=sys.stderr)
        raise SystemExit(2)
    return key


def redact(text: str, secret: str) -> str:
    """Remove a secret from text before it is printed."""
    return text.replace(secret, "[redacted]") if secret else text


def ssl_context() -> ssl.SSLContext:
    """TLS context that verifies certificates without SSL_CERT_FILE.

    uv-managed and python.org Pythons on macOS may have no CA bundle, so
    urllib fails with CERTIFICATE_VERIFY_FAILED. Run the scripts with
    ``uv run --with certifi`` to use certifi's bundle; without certifi the
    system default is used.
    """
    try:
        # Optional: present only when run with `uv run --with certifi`.
        certifi = importlib.import_module("certifi")
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


@dataclass(frozen=True)
class Reply:
    """HTTP status and parsed JSON body (or the raw text if not JSON)."""

    status: int
    body: Any


def post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout: float = 120,
) -> Reply:
    """POST JSON and return the status and body; HTTP errors are returned too."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=ssl_context()
        ) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except (urllib.error.URLError, TimeoutError) as error:
        return Reply(0, f"connection failed: {error}")
    text = raw.decode("utf-8", errors="replace")
    try:
        return Reply(status, json.loads(text))
    except json.JSONDecodeError:
        return Reply(status, text)


def print_failure(title: str, status: int, body: object, key: str) -> None:
    """Print an HTTP failure with the key removed from the body."""
    print(f"--- {title}")
    print(f"FAIL: HTTP {status}: {redact(str(body), key)[:800]}")


def report(
    title: str, text: str | None, schema: Mapping[str, Any], usage: object
) -> bool:
    """Print whether the model's JSON text is valid against the schema."""
    print(f"--- {title}")
    print(f"usage: {json.dumps(usage)}")
    if text is None:
        print("FAIL: no JSON text in the reply")
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        print(f"FAIL: reply is not JSON ({error})")
        return False
    errors = schema_errors(data, schema)
    if errors:
        print("FAIL: " + "; ".join(errors[:5]))
        return False
    print("PASS: schema-valid JSON")
    print(json.dumps(data, indent=2)[:1500])
    return True
