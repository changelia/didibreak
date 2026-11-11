"""check validates the LLM settings before cases are needed (exit 2)."""

import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from conftest import GitRepository

from didibreak import cli, llm
from didibreak.cli import EXIT_ERROR, EXIT_OK, main
from didibreak.config import Config


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Answer every LLM request with an empty case list; record the URLs."""
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        text = json.dumps({"cases": []})
        if request.url.path.endswith("/messages"):
            body = {
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
            }
        else:
            body = {
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}]
            }
        return httpx.Response(200, json=body)

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    monkeypatch.setattr(cli, "create_client", create)
    return urls


@pytest.fixture
def changed_function(
    git_repository: GitRepository, monkeypatch: pytest.MonkeyPatch
) -> Path:
    git_repository.write("app.py", "def f(x):\n    return x\n")
    git_repository.commit()
    git_repository.write("app.py", "def f(x):\n    return x + 1\n")
    monkeypatch.chdir(git_repository.path)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MY_LLM_KEY"):
        monkeypatch.delenv(name, raising=False)
    return git_repository.path


def test_missing_provider_exits_2_with_how_to_fix(
    changed_function: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check"]) == EXIT_ERROR
    assert "set provider (openai, anthropic," in "".join(capsys.readouterr())


def test_missing_key_exits_2_naming_the_variable(
    changed_function: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--provider", "anthropic"]) == EXIT_ERROR
    assert "set the environment variable ANTHROPIC_API_KEY" in "".join(
        capsys.readouterr()
    )


def test_custom_key_variable_is_named(
    changed_function: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (changed_function / "pyproject.toml").write_text(
        '[tool.didibreak]\nprovider = "openai"\napi_key_env = "MY_LLM_KEY"\n',
        encoding="utf-8",
    )

    assert main(["check"]) == EXIT_ERROR
    assert "MY_LLM_KEY" in "".join(capsys.readouterr())


def test_custom_base_url_without_model_exits_2(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    argv = ["check", "--provider", "openai", "--base-url", "http://localhost:11434/v1"]

    assert main(argv) == EXIT_ERROR
    assert "set model" in "".join(capsys.readouterr())


def test_complete_settings_reach_the_llm_without_showing_the_key(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    fake_llm: list[str],
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-in-env")

    assert main(["check", "--provider", "openai"]) == EXIT_OK
    err = "".join(capsys.readouterr())
    assert fake_llm == ["https://api.openai.com/v1/chat/completions"]
    assert "app.py::f (no valid cases)" in err
    assert "sk-secret-in-env" not in err


def test_cases_file_runs_need_no_llm_settings(
    changed_function: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = tmp_path / "cases.json"
    cases.write_text('{"cases": [{"function": "app.py::f", "args": ["1"]}]}')

    assert main(["check", "--cases-file", str(cases)]) == 1  # one unclear finding
    assert "provider" not in "".join(capsys.readouterr())


def test_provider_is_inferred_from_the_only_key_set(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    fake_llm: list[str],
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-only")

    assert main(["check"]) == EXIT_OK
    assert fake_llm == ["https://api.anthropic.com/v1/messages"]
    assert "provider" not in "".join(capsys.readouterr())


def test_both_keys_without_provider_exit_2(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-2")

    assert main(["check"]) == EXIT_ERROR
    assert "both OPENAI_API_KEY and ANTHROPIC_API_KEY are set" in "".join(
        capsys.readouterr()
    )


@pytest.fixture
def no_llm_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_nothing_to_check_needs_no_llm_settings(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    no_llm_settings: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git_repository.write("app.py", "def f(x):\n    return x\n")
    git_repository.commit()
    monkeypatch.chdir(git_repository.path)

    assert main(["check"]) == EXIT_OK
    assert "Nothing to check" in "".join(capsys.readouterr())


def test_only_skipped_functions_need_no_llm_settings(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    no_llm_settings: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git_repository.write("app.py", "async def f(x):\n    return x\n")
    git_repository.commit()
    git_repository.write("app.py", "async def f(x):\n    return x + 1\n")
    monkeypatch.chdir(git_repository.path)

    assert main(["check"]) == EXIT_OK
    err = "".join(capsys.readouterr())
    assert "checked 0 functions" in err
    assert "provider" not in err
