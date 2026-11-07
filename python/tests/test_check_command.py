"""Tests for the check and init-agents commands, config precedence and exit codes."""

import contextlib
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak import cli
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
from didibreak.llm.common import TokenUsage
from didibreak.pipeline import Analysis, Generation


@pytest.fixture(autouse=True)
def llm_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # These tests cover detection and exit codes; LLM settings are checked in
    # test_check_llm_settings.py and LLM case generation in
    # test_check_llm_end_to_end.py. Here the LLM proposes no cases.
    def no_session(*arguments: object) -> object:
        return contextlib.nullcontext()

    def no_cases(*arguments: object) -> object:
        empty = Analysis((), (), (), 0, 0, 0)
        return empty, cli._LLMCases(Generation({}, (), 0, TokenUsage()))

    monkeypatch.setattr("didibreak.cli._start_llm", no_session)
    monkeypatch.setattr("didibreak.cli._check_with_llm", no_cases)


@pytest.fixture
def repository(git_repository: GitRepository, monkeypatch: pytest.MonkeyPatch) -> Path:
    git_repository.write("app.py", "VALUE = 1\n")
    git_repository.commit("initial")
    monkeypatch.chdir(git_repository.path)
    return git_repository.path


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
    assert "Nothing to check" in capsys.readouterr().err


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
    (package / ".venv/bin").mkdir(parents=True)
    (package / ".venv/bin/python").write_text("", encoding="utf-8")
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
        _cli_values(["--output-dir", "out", "--python", sys.executable]),
        working_directory,
    )

    assert config.output_dir == str(working_directory / "out")
    assert config.python == sys.executable


def _fake_interpreter(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_bare_python_name_is_looked_up_on_path(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interpreter = _fake_interpreter(tmp_path / "bin", "python-for-didibreak")
    monkeypatch.setenv("PATH", f"{interpreter.parent}{os.pathsep}{os.environ['PATH']}")

    config = load_config(_cli_values(["--python", "python-for-didibreak"]), repository)

    assert config.python == str(interpreter)


def test_bare_python_name_in_pyproject_is_looked_up_on_path(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interpreter = _fake_interpreter(tmp_path / "bin", "python-for-didibreak")
    monkeypatch.setenv("PATH", f"{interpreter.parent}{os.pathsep}{os.environ['PATH']}")
    (repository / "pyproject.toml").write_text(
        '[tool.didibreak]\npython = "python-for-didibreak"\n', encoding="utf-8"
    )

    assert load_config({}, repository).python == str(interpreter)


def test_python_name_missing_from_path_exits_with_error(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--python", "no-such-python-9"]) == EXIT_ERROR
    assert "'no-such-python-9' was not found on PATH" in capsys.readouterr().err


def test_python_path_that_does_not_exist_exits_with_error(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "pyproject.toml").write_text(
        '[tool.didibreak]\npython = "venv/bin/python"\n', encoding="utf-8"
    )

    assert main(["check"]) == EXIT_ERROR
    error_output = capsys.readouterr().err
    assert "[tool.didibreak] in" in error_output
    assert "venv/bin/python' does not exist" in error_output


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
        (["expected"], "unclear", EXIT_OK),
        (["expected", "new_function"], "unclear", EXIT_FINDINGS),
        (["new_function"], "unexpected", EXIT_OK),
        (["unclear"], "unclear", EXIT_FINDINGS),
        (["unclear"], "unexpected", EXIT_OK),
        (["expected", "unexpected"], "unexpected", EXIT_FINDINGS),
    ],
)
def test_exit_code_follows_labels_and_fail_on(
    labels: list[str], fail_on: str, expected: int
) -> None:
    assert exit_code_for(labels, fail_on) == expected


def test_check_counts_changed_and_new_functions(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "lib.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "lib.py"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "lib"], cwd=repository, check=True)
    (repository / "lib.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (repository / "new.py").write_text("def g():\n    return 1\n", encoding="utf-8")

    assert main(["check", "-v"]) == EXIT_OK

    error_output = capsys.readouterr().err
    assert "2 changed function(s) to check (1 new)" in error_output
    assert "  changed: lib.py::f\n  new: new.py::g" in error_output


def test_check_with_only_constant_changes_has_nothing_to_check(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert main(["check"]) == EXIT_OK
    assert "no changed Python functions" in capsys.readouterr().err


def test_check_reports_functions_cut_by_the_limit(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "".join(f"def f{n}():\n    return {n}\n\n\n" for n in range(3))
    (repository / "many.py").write_text(body, encoding="utf-8")

    assert main(["check", "--max-functions", "2", "-v"]) == EXIT_OK

    error_output = capsys.readouterr().err
    assert "1 more not checked (max_functions = 2)" in error_output
    assert "  limit: many.py::f2" in error_output


def test_check_reports_files_with_syntax_errors_and_deleted_files(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (repository / "app.py").unlink()

    assert main(["check"]) == EXIT_OK

    error_output = capsys.readouterr().err
    assert "skipped broken.py: syntax error in the current version, line 1" in (
        error_output
    )


def test_check_with_unknown_base_exits_with_error(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--base", "no-such-branch"]) == EXIT_ERROR
    assert "unknown base ref 'no-such-branch'" in capsys.readouterr().err


def test_check_in_a_repository_without_commits_exits_with_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = GitRepository(tmp_path / "empty")
    monkeypatch.chdir(empty.path)

    assert main(["check"]) == EXIT_ERROR
    assert "has no commits yet" in capsys.readouterr().err


def _change_with_exclusions(repository: Path) -> None:
    for path in ("tests/test_app.py", "conftest.py"):
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("X = 1\n", encoding="utf-8")


def test_check_reports_the_number_of_excluded_files(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _change_with_exclusions(repository)

    assert main(["check"]) == EXIT_OK

    error_output = capsys.readouterr().err
    assert "2 files excluded" in error_output
    assert "excluded: conftest.py" not in error_output


def test_verbose_check_lists_excluded_files(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _change_with_exclusions(repository)

    assert main(["check", "-v"]) == EXIT_OK

    error_output = capsys.readouterr().err
    assert "  excluded: conftest.py\n  excluded: tests/test_app.py" in error_output


def test_json_format_does_not_print_the_exclusion_line(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _change_with_exclusions(repository)

    assert main(["check", "--format", "json"]) == EXIT_OK
    assert "excluded" not in capsys.readouterr().err


def test_check_reports_skipped_functions_with_reasons_in_verbose_mode(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "mixed.py").write_text(
        "import subprocess\n\n\ndef pure():\n    return 1\n\n\n"
        "def run():\n    return subprocess.run(['ls'])\n",
        encoding="utf-8",
    )

    assert main(["check", "-v"]) == EXIT_OK

    error_output = capsys.readouterr().err
    assert "1 function(s) skipped: not testable in v0.1" in error_output
    assert "  skipped: mixed.py::run (obvious I/O: subprocess.run)" in error_output
    assert "  new: mixed.py::pure" in error_output


def test_check_warns_when_all_changed_functions_are_skipped(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repository / "gen.py").write_text(
        "def numbers():\n    yield 1\n", encoding="utf-8"
    )

    assert main(["check"]) == EXIT_OK

    error_output = capsys.readouterr().err
    assert "Warning: checked 0 functions" in error_output
    assert "  skipped: gen.py::numbers (generator)" in error_output
    assert "Nothing to check" not in error_output
