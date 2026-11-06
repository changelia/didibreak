"""scripts/llm_smoke.py with a mocked transport (no network)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "llm_smoke.py"
KEY = "sk-smoke-secret-0123456789"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("llm_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reply(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gpt-6-luna",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 168,
                "completion_tokens": 112,
                "completion_tokens_details": {"reasoning_tokens": 30},
            },
        },
    )


def test_pass_is_written_with_usage_and_without_the_key(tmp_path: Path) -> None:
    smoke = load_script()
    labels = {"labels": [{"finding_id": "f1", "label": "expected", "reason": "r"}]}
    output = tmp_path / "out.txt"

    code = smoke.run(
        output,
        {"OPENAI_API_KEY": KEY},
        transport=httpx.MockTransport(lambda request: reply(json.dumps(labels))),
    )

    text = output.read_text()
    assert code == 0
    assert "model requested: gpt-6-luna" in text
    assert "PASS: schema-valid JSON" in text
    assert "output_tokens=112 reasoning_tokens=30" in text
    assert "SSL_CERT_FILE set: no" in text
    assert KEY not in text


def test_failure_is_written_without_the_key(tmp_path: Path) -> None:
    smoke = load_script()
    output = tmp_path / "out.txt"
    rejected = httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}})

    code = smoke.run(
        output,
        {"OPENAI_API_KEY": KEY},
        transport=httpx.MockTransport(lambda r: rejected),
    )

    text = output.read_text()
    assert code == 1
    assert "FAIL (LLMAuthError)" in text
    assert KEY not in text


@pytest.mark.parametrize("environment", [{}, {"OPENAI_API_KEY": ""}])
def test_missing_key_is_reported_without_a_call(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    smoke = load_script()
    output = tmp_path / "out.txt"

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    code = smoke.run(output, environment, transport=httpx.MockTransport(no_network))

    assert code == 2
    assert "OPENAI_API_KEY" in output.read_text()
