"""The task 12 spike helpers: schema check, payloads, key handling (no network)."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SPIKE = Path(__file__).resolve().parents[1] / "spike"
if not SPIKE.is_dir():  # the sdist ships tests but not the spike scripts
    pytest.skip(
        "spike/ not found: needs the repository checkout", allow_module_level=True
    )
sys.path.insert(0, str(SPIKE))

import openai_compatible  # noqa: E402
import spike_anthropic  # noqa: E402
import spike_common  # noqa: E402
from spike_common import CASES_SCHEMA, LABELS_SCHEMA, Reply, schema_errors  # noqa: E402

VALID_CASES = {
    "cases": [
        {
            "args": ["'995 555 12 34 56'"],
            "kwargs": [{"name": "strict", "value": "True"}],
            "rationale": "country code without plus",
        }
    ]
}
VALID_LABELS = {"labels": [{"finding_id": "f1", "label": "expected", "reason": "r"}]}
KEY = "sk-test-secret-123"


def test_valid_replies_match_the_schemas() -> None:
    assert schema_errors(VALID_CASES, CASES_SCHEMA) == []
    assert schema_errors(VALID_LABELS, LABELS_SCHEMA) == []


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"cases": [{"args": [1], "kwargs": [], "rationale": ""}]},
        {"cases": [{"args": [], "kwargs": {"x": "1"}, "rationale": ""}]},
        {"cases": [{"args": [], "kwargs": [], "rationale": "", "extra": 1}]},
    ],
)
def test_invalid_case_replies_are_rejected(reply: object) -> None:
    assert schema_errors(reply, CASES_SCHEMA)


def test_labels_outside_the_enum_are_rejected() -> None:
    reply = {"labels": [{"finding_id": "f1", "label": "maybe", "reason": "r"}]}

    assert schema_errors(reply, LABELS_SCHEMA)


def test_every_object_in_the_schemas_is_strict() -> None:
    # Strict structured output requires additionalProperties false everywhere.
    def objects(schema: Any) -> list[Any]:
        found = [schema] if schema.get("type") == "object" else []
        for child in schema.get("properties", {}).values():
            found += objects(child)
        if "items" in schema:
            found += objects(schema["items"])
        return found

    for schema in (CASES_SCHEMA, LABELS_SCHEMA):
        for item in objects(schema):
            assert item["additionalProperties"] is False
            assert set(item["required"]) == set(item["properties"])


def test_missing_key_exits_without_sending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        spike_common.api_key("OPENAI_API_KEY")

    assert exit_info.value.code == 2
    assert "nothing was sent" in capsys.readouterr().err


def test_chat_payload_asks_for_strict_json_schema() -> None:
    payload = openai_compatible.chat_payload("m", "p", "n", CASES_SCHEMA)

    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "n", "strict": True, "schema": CASES_SCHEMA},
    }


def test_anthropic_payload_uses_output_config_and_no_sampling() -> None:
    payload = spike_anthropic.messages_payload("m", "p", CASES_SCHEMA)

    assert payload["output_config"] == {
        "format": {"type": "json_schema", "schema": CASES_SCHEMA}
    }
    assert not {"temperature", "top_p", "top_k"} & set(payload)


def test_refusals_and_cut_off_replies_give_no_text() -> None:
    refused = {"choices": [{"message": {"refusal": "no", "content": None}}]}

    assert openai_compatible.reply_text(refused) is None
    assert spike_anthropic.reply_text({"stop_reason": "refusal"}) is None
    assert spike_anthropic.reply_text({"stop_reason": "max_tokens"}) is None


def test_run_passes_on_valid_replies_and_never_prints_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent: list[dict[str, Any]] = []

    def fake_post(url: str, headers: dict[str, str], payload: Any) -> Reply:
        sent.append({"url": url, "headers": headers, "payload": payload})
        name = payload["response_format"]["json_schema"]["name"]
        content = VALID_CASES if name == "didibreak_cases" else VALID_LABELS
        message = {"content": json.dumps(content), "refusal": None}
        return Reply(200, {"choices": [{"message": message}], "usage": {"x": 1}})

    monkeypatch.setattr(openai_compatible, "post_json", fake_post)

    code = openai_compatible.run("https://example.test/v1", "m", KEY)

    assert code == 0
    assert sent[0]["url"] == "https://example.test/v1/chat/completions"
    assert sent[0]["headers"] == {"authorization": f"Bearer {KEY}"}
    assert sent[-1]["payload"]["temperature"] == 0  # the probe
    out = capsys.readouterr().out
    assert out.count("PASS") == 2
    assert KEY not in out


def test_errors_are_printed_with_the_key_removed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_post(url: str, headers: dict[str, str], payload: Any) -> Reply:
        return Reply(401, {"error": f"bad key {KEY}"})

    monkeypatch.setattr(openai_compatible, "post_json", fake_post)

    assert openai_compatible.run("https://example.test/v1", "m", KEY) == 1
    out = capsys.readouterr().out
    assert "HTTP 401" in out
    assert KEY not in out
    assert "[redacted]" in out
