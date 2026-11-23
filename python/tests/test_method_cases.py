"""Method cases carry constructor arguments through every entry point (task 30)."""

import json
from pathlib import Path

import pytest

from didibreak.arguments import format_case_call
from didibreak.cache import CaseCache
from didibreak.cases import describe_call
from didibreak.compare import finding_id
from didibreak.config import ConfigError
from didibreak.functions import ChangedFunction
from didibreak.harness import Case, case_call
from didibreak.pipeline import load_cases_file

METHOD = ChangedFunction(
    file="app/bank.py",
    module="app.bank",
    qualname="Account.deposit",
    kind="changed",
    function_type="method",
    is_async=False,
    line=5,
    old_source="def deposit(self, amount):\n    self.balance += amount\n",
    new_source="def deposit(self, amount):\n    self.balance += abs(amount)\n",
)
METHOD_CASE = Case(("-5",), {}, "negative", ("100",), {"owner": "'ada'"})


def test_a_method_case_is_printed_with_its_constructor() -> None:
    assert (
        case_call("app/bank.py::Account.deposit", METHOD_CASE)
        == "app/bank.py::Account(100, owner='ada').deposit(-5)"
    )
    assert describe_call("Account.deposit", METHOD_CASE) == (
        "Account(100, owner='ada').deposit(-5)"
    )


def test_a_constructor_without_arguments_still_shows_the_instance() -> None:
    assert format_case_call("C.m", ("1",), {}, (), {}) == "C().m(1)"


def test_a_function_case_is_printed_as_before() -> None:
    case = Case(("1",), {"k": "2"})

    assert case_call("a.py::f", case) == "a.py::f(1, k=2)"
    assert not case.is_method_case


def test_a_function_finding_keeps_the_id_it_had_before_task_30() -> None:
    # Same id as in the reproducing-test fixtures (phone_regression).
    case = Case(("'995 555 12 34 56'",))

    assert finding_id("app/utils/phone.py::normalize_phone", case) == "30040f8bc543"


def test_constructor_arguments_are_part_of_a_method_finding_id() -> None:
    plain = finding_id("a.py::C.m", Case(("1",)))
    no_arguments = finding_id("a.py::C.m", Case(("1",), init_args=()))
    other = finding_id("a.py::C.m", Case(("1",), init_args=("2",)))

    assert len({plain, no_arguments, other}) == 3
    assert finding_id("a.py::C.m", Case(("1",), init_args=("'x'",))) == finding_id(
        "a.py::C.m", Case(("1",), init_args=('"x"',))
    )


def test_method_cases_round_trip_through_the_cache(tmp_path: Path) -> None:
    store = CaseCache(tmp_path / ".didibreak", "openai", "gpt-6-luna", 1)
    cases = (METHOD_CASE, Case(("1",), {}, "no constructor arguments", ()))

    assert store.store(METHOD, 12, cases)
    assert store.load(METHOD, 12) == cases


def test_a_cached_constructor_argument_that_is_code_spoils_the_entry(
    tmp_path: Path,
) -> None:
    store = CaseCache(tmp_path / ".didibreak", "openai", "gpt-6-luna", 1)
    store.store(METHOD, 12, (METHOD_CASE,))
    path = next(store.folder.glob("*.json"))
    data = json.loads(path.read_text())
    data["cases"][0]["init_args"] = ["__import__('os')"]
    path.write_text(json.dumps(data))

    assert store.load(METHOD, 12) is None


def write_cases(tmp_path: Path, case: dict[str, object]) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [{"function": "a.py::C.m", **case}]}))
    return path


def test_the_cases_file_reads_constructor_arguments(tmp_path: Path) -> None:
    path = write_cases(
        tmp_path, {"args": ["1"], "init_args": ["2  # two"], "init_kwargs": {"k": "3"}}
    )

    assert load_cases_file(path) == {
        "a.py::C.m": (Case(("1",), {}, "", ("2",), {"k": "3"}),)
    }


def test_init_kwargs_alone_make_a_method_case(tmp_path: Path) -> None:
    path = write_cases(tmp_path, {"args": [], "init_kwargs": {"k": "3"}})

    (case,) = load_cases_file(path)["a.py::C.m"]
    assert case.init_args == ()
    assert case.init_kwargs == {"k": "3"}


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ({"init_args": ["open('x')"]}, "constructor argument: not a Python literal"),
        ({"init_args": "1"}, '"init_args" must be a list of strings'),
        ({"init_kwargs": {"class": "1"}}, "unusable keyword name"),
        ({"init_kwargs": {"k": 1}}, '"init_kwargs" must map names to strings'),
    ],
)
def test_a_bad_constructor_argument_in_the_cases_file_is_an_error(
    tmp_path: Path, case: dict[str, object], message: str
) -> None:
    path = write_cases(tmp_path, {"args": ["1"], **case})

    with pytest.raises(ConfigError, match=message):
        load_cases_file(path)
