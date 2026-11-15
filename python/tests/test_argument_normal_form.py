"""Case arguments are stored in a normal form (pre-launch review, finding 12).

``ast.literal_eval`` accepts ``2  # a comment``; pasted into a call, the
comment swallowed the rest of the line and the generated test file did not
compile, so the tests of the other findings were lost too.
"""

import ast
import json
from pathlib import Path

import pytest
from conftest import GitRepository

from didibreak import cache, cases, pipeline
from didibreak.arguments import (
    MAX_ARGUMENT_LENGTH,
    format_call,
    literal_problem,
    normal_form,
)
from didibreak.cli import EXIT_FINDINGS, main

COMMENT = "2  # the smallest even prime"
SOURCE_BREAKING = [
    (COMMENT, "2"),
    ("  7", "7"),
    ("'a' # ) + oops(", "'a'"),
    ("[1,\n 2,  # second\n 3]", "[1, 2, 3]"),
    ("'''two\nlines'''", "'two\\nlines'"),
    ("(1,\n)", "(1,)"),
    ('"quoted"', "'quoted'"),
    ("-(1)", "-1"),
    ("1_000", "1000"),
    ("{'k': 'v' # why\n}", "{'k': 'v'}"),
    ("b'a' b'b'", "b'ab'"),
]


@pytest.mark.parametrize(("text", "normal"), SOURCE_BREAKING)
def test_normal_form_is_one_safe_expression(text: str, normal: str) -> None:
    assert normal_form(text) == normal
    assert ast.literal_eval(normal) == ast.literal_eval(text)
    assert normal_form(normal) == normal  # stable
    assert "\n" not in normal and "#" not in normal.replace("'#'", "")


def test_a_hash_inside_a_string_is_kept() -> None:
    assert normal_form("'# not a comment'  # a comment") == "'# not a comment'"


@pytest.mark.parametrize("text", ["f(1)", "1 +", "x", "", "__import__('os')"])
def test_text_that_is_not_a_literal_is_still_rejected(text: str) -> None:
    assert literal_problem(text) == f"not a Python literal: {text!r}"


def test_an_argument_that_grows_past_the_limit_in_normal_form_is_rejected() -> None:
    # "\0" is 2 characters as written and 4 ("\x00") in the normal form.
    text = "'" + "\\0" * (MAX_ARGUMENT_LENGTH // 2 - 1) + "'"

    assert len(text) <= MAX_ARGUMENT_LENGTH
    assert literal_problem(text) == f"longer than {MAX_ARGUMENT_LENGTH} characters"


def test_every_entry_point_stores_the_normal_form() -> None:
    reply = {"cases": [{"args": [COMMENT], "kwargs": [{"name": "k", "value": " 1"}]}]}
    from_llm = cases.accept_cases(reply, 5, "a.py::f").cases[0]
    item = {"function": "a.py::f", "args": [COMMENT], "kwargs": {"k": " 1"}}
    _, from_file = pipeline._case(item, 1)
    from_cache = cache._case_from_json({"args": [COMMENT], "kwargs": {"k": " 1"}})

    assert from_cache is not None
    for case in (from_llm, from_file, from_cache):
        assert (case.args, dict(case.kwargs)) == (("2",), {"k": "1"})


def test_format_call_is_safe_for_a_case_built_by_hand() -> None:
    call = format_call("double", [COMMENT, "1"], {"k": "3 # x"})

    assert call == "double(2, 1, k=3)"
    ast.parse(call)


def test_format_call_shows_text_that_is_no_expression_as_it_is() -> None:
    assert format_call("f", ["1 +"], {}) == "f(1 +)"


def test_a_comment_in_an_argument_cannot_break_the_test_file(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The review's reproduction: the first case carries the comment.
    source = "def double(x, y=0):\n    return x * {factor} + y\n"
    git_repository.write("app/run.py", source.format(factor=2))
    git_repository.commit("base")
    git_repository.write("app/run.py", source.format(factor=3))
    function = "app/run.py::double"
    listed = [
        {"function": function, "args": [COMMENT, "1"], "kwargs": {}},
        {"function": function, "args": ["5"], "kwargs": {"y": "1 # one"}},
    ]
    path = git_repository.write("cases.json", json.dumps({"cases": listed}))
    monkeypatch.chdir(git_repository.path)

    assert main(["check", "--cases-file", str(path)]) == EXIT_FINDINGS

    out = capsys.readouterr().out
    assert "app/run.py::double(2, 1)" in out
    assert "app/run.py::double(5, y=1)" in out
    assert "#" not in out
    test_file = Path(".didibreak/tests/test_double.py")
    text = test_file.read_text(encoding="utf-8")
    compile(text, str(test_file), "exec")  # SyntaxError before the fix
    assert "    result = double(2, 1)\n" in text
    assert "    result = double(5, y=1)\n" in text
    assert text.count("def test_double_") == 2


def test_the_json_report_holds_the_normal_form(
    git_repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git_repository.write("app/run.py", "def double(x):\n    return x * 2\n")
    git_repository.commit("base")
    git_repository.write("app/run.py", "def double(x):\n    return x * 3\n")
    case = {"function": "app/run.py::double", "args": [COMMENT], "kwargs": {}}
    path = git_repository.write("cases.json", json.dumps({"cases": [case]}))
    monkeypatch.chdir(git_repository.path)

    main(["check", "--cases-file", str(path), "--format", "json"])

    assert json.loads(capsys.readouterr().out)["findings"][0]["args"] == ["2"]
