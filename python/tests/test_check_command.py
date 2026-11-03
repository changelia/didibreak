"""Tests for the check and init-agents commands, config precedence and exit codes."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from didibreak.cli import (
    AGENT_SNIPPET,
    EXIT_ERROR,
    EXIT_FINDINGS,
    EXIT_OK,
    build_parser,
    exit_code_for,
    load_config,
    main,
)
from didibreak.config import CONFIG_KEYS, Config
from didibreak.gitdiff import repository_root


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    monkeypatch.chdir(path)
    return path


def _cli_values(argv: list[str]) -> dict[str, object]:
    arguments = build_parser().parse_args(["check", *argv])
    return {
        key: getattr(arguments, key) for key in CONFIG_KEYS if hasattr(arguments, key)
    }


def test_check_without_pyproject_uses_defaults_and_succeeds(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repository_root(repository)
    expected = replace(Config(), output_dir=str(root / ".didibreak"))
    assert load_config({}, repository) == expected

    assert main(["check"]) == EXIT_OK
    assert "configuration OK" in capsys.readouterr().err


def test_flags_override_pyproject_which_overrides_defaults(repository: Path) -> None:
    (repository / "pyproject.toml").write_text(
        "[tool.didibreak]\ncases = 20\nmax_functions = 3\n", encoding="utf-8"
    )

    config = load_config(_cli_values(["--cases", "5", "--no-cache"]), repository)

    assert (config.cases, config.max_functions, config.no_cache) == (5, 3, True)
    assert config.refine_rounds == 1


def test_relative_paths_in_pyproject_are_relative_to_that_file(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = repository / "python"
    (package / "src").mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        '[tool.didibreak]\noutput_dir = "out"\npython = ".venv/bin/python"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(package / "src")

    config = load_config({}, package / "src")

    assert config.output_dir == str(package / "out")
    assert config.python == str(package / ".venv/bin/python")


def test_relative_paths_in_flags_are_relative_to_the_working_directory(
    repository: Path,
) -> None:
    (repository / "pyproject.toml").write_text(
        '[tool.didibreak]\noutput_dir = "from-file"\n', encoding="utf-8"
    )
    working_directory = repository / "app"
    working_directory.mkdir()

    config = load_config(
        _cli_values(["--output-dir", "out", "--python", "/usr/bin/python3"]),
        working_directory,
    )

    assert config.output_dir == str(working_directory / "out")
    assert config.python == "/usr/bin/python3"


def test_default_output_dir_is_at_the_repository_root(repository: Path) -> None:
    subdirectory = repository / "deep" / "inside"
    subdirectory.mkdir(parents=True)

    config = load_config({}, subdirectory)

    assert config.output_dir == str(repository_root(repository) / ".didibreak")


def test_only_given_flags_become_overrides() -> None:
    assert _cli_values([]) == {}
    assert _cli_values(["--format", "json"]) == {"format": "json"}


def test_check_outside_a_repository_exits_with_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["check"]) == EXIT_ERROR
    assert "is not inside a git repository" in capsys.readouterr().err


def test_invalid_pyproject_value_exits_with_error(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "pyproject.toml").write_text(
        '[tool.didibreak]\nformat = "xml"\n', encoding="utf-8"
    )

    assert main(["check"]) == EXIT_ERROR
    assert "format must be one of text, json; got 'xml'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--cases", "0"], "cases must be >= 1 and <= 50; got 0"),
        (["--cases", "many"], "cases: invalid value 'many'"),
        (["--provider", "gemini"], "provider must be one of openai, anthropic"),
        (["-v", "-q"], "not allowed with argument"),
    ],
)
def test_invalid_flags_exit_with_usage_error(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["check", *argv])

    assert exit_info.value.code == EXIT_ERROR
    assert message in capsys.readouterr().err


def test_cases_file_option_is_hidden_from_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["check", "--help"])

    assert "--cases-file" not in capsys.readouterr().out


def test_init_agents_prints_the_snippet_from_the_spec(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["init-agents"]) == EXIT_OK

    output = capsys.readouterr().out
    assert output == AGENT_SNIPPET
    assert output.startswith("## Behavior check\n")
    assert "--format json\n" in output


@pytest.mark.parametrize(
    ("labels", "fail_on", "expected"),
    [
        ([], "unclear", EXIT_OK),
        (["expected", "new_function"], "unclear", EXIT_OK),
        (["unclear"], "unclear", EXIT_FINDINGS),
        (["unclear"], "unexpected", EXIT_OK),
        (["expected", "unexpected"], "unexpected", EXIT_FINDINGS),
    ],
)
def test_exit_code_follows_labels_and_fail_on(
    labels: list[str], fail_on: str, expected: int
) -> None:
    assert exit_code_for(labels, fail_on) == expected
