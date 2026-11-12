import json
from pathlib import Path

import pytest

from didibreak.config import ConfigError
from didibreak.harness import Case
from didibreak.pipeline import load_cases_file


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_cases_are_grouped_by_function_in_file_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {
            "cases": [
                {"function": "a.py::f", "args": ["1"], "rationale": "one"},
                {"function": "b.py::g", "args": [], "kwargs": {"x": "'s'"}},
                {"function": "a.py::f", "args": ["2"]},
            ]
        },
    )

    assert load_cases_file(path) == {
        "a.py::f": (Case(("1",), {}, "one"), Case(("2",))),
        "b.py::g": (Case((), {"x": "'s'"}),),
    }


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], 'expected {"cases": [...]}'),
        ({"cases": [1]}, "case 1: expected an object"),
        ({"cases": [{"function": "f"}]}, 'case 1: "function" must be'),
        ({"cases": [{"function": "a.py::f", "args": [1]}]}, '"args" must be'),
        ({"cases": [{"function": "a.py::f", "kwargs": {"x": 1}}]}, '"kwargs" must'),
        ({"cases": [{"function": "a.py::f", "rationale": 1}]}, '"rationale" must'),
        (
            {"cases": [{"function": "a.py::f", "args": ["__import__('os')"]}]},
            "case 1: not a Python literal",
        ),
        # Same rule as LLM replies since task 35c (audit 35a, finding 11).
        (
            {"cases": [{"function": "a.py::f", "kwargs": {"class": "1"}}]},
            "case 1: unusable keyword name 'class'",
        ),
        (
            {"cases": [{"function": "a.py::f", "args": ["'" + "a" * 3000 + "'"]}]},
            "case 1: longer than 2000 characters",
        ),
    ],
)
def test_invalid_files_name_the_file_and_the_problem(
    tmp_path: Path, data: object, message: str
) -> None:
    path = write(tmp_path, data)

    with pytest.raises(ConfigError, match=r"cases file .*cases\.json") as error:
        load_cases_file(path)

    assert message in str(error.value)


def test_unreadable_files_are_configuration_errors(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(ConfigError, match="cannot read it"):
        load_cases_file(tmp_path / "broken.json")
    with pytest.raises(ConfigError, match="cannot read it"):
        load_cases_file(tmp_path / "missing.json")
