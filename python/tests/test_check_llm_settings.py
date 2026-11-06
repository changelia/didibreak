"""check validates the LLM settings before cases are needed (exit 2)."""

from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak.cli import EXIT_ERROR, EXIT_OK, main


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
    assert 'set provider = "openai" or "anthropic"' in capsys.readouterr().err


def test_missing_key_exits_2_naming_the_variable(
    changed_function: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--provider", "anthropic"]) == EXIT_ERROR
    assert "set the environment variable ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_custom_key_variable_is_named(
    changed_function: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (changed_function / "pyproject.toml").write_text(
        '[tool.didibreak]\nprovider = "openai"\napi_key_env = "MY_LLM_KEY"\n',
        encoding="utf-8",
    )

    assert main(["check"]) == EXIT_ERROR
    assert "MY_LLM_KEY" in capsys.readouterr().err


def test_custom_base_url_without_model_exits_2(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    argv = ["check", "--provider", "openai", "--base-url", "http://localhost:11434/v1"]

    assert main(argv) == EXIT_ERROR
    assert "set model" in capsys.readouterr().err


def test_complete_settings_continue_without_showing_the_key(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-in-env")

    assert main(["check", "--provider", "openai"]) == EXIT_OK
    err = capsys.readouterr().err
    assert "not implemented yet" in err
    assert "sk-secret-in-env" not in err


def test_cases_file_runs_need_no_llm_settings(
    changed_function: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = tmp_path / "cases.json"
    cases.write_text('{"cases": [{"function": "app.py::f", "args": ["1"]}]}')

    assert main(["check", "--cases-file", str(cases)]) == 1  # one unclear finding
    assert "provider" not in capsys.readouterr().err


def test_provider_is_inferred_from_the_only_key_set(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-only")

    assert main(["check"]) == EXIT_OK
    assert "provider" not in capsys.readouterr().err


def test_both_keys_without_provider_exit_2(
    changed_function: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-2")

    assert main(["check"]) == EXIT_ERROR
    assert (
        "both OPENAI_API_KEY and ANTHROPIC_API_KEY are set" in capsys.readouterr().err
    )
