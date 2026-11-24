"""Deterministic boundary cases for simple annotations (task 31)."""

import ast

import pytest

from didibreak.boundary import annotation_values, boundary_cases
from didibreak.compare import finding_id
from didibreak.functions import ChangedFunction
from didibreak.harness import Case


def function(
    source: str, function_type: str = "function", qualname: str = "f"
) -> ChangedFunction:
    return ChangedFunction(
        file="app/m.py",
        module="app.m",
        qualname=qualname,
        kind="changed",
        function_type=function_type,
        is_async=False,
        line=1,
        old_source=source,
        new_source=source,
    )


def values(annotation: str) -> tuple[object, tuple[object, ...]] | None:
    found = annotation_values(ast.parse(annotation, mode="eval").body)
    return None if found is None else (found.typical, found.boundaries)


def calls(cases: tuple[Case, ...]) -> list[tuple[tuple[str, ...], dict[str, str]]]:
    return [(case.args, dict(case.kwargs)) for case in cases]


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("int", (1, (0, -1, 2**31))),
        ("float", (1.5, (0.0, -1.0, 1e16))),
        ("str", ("abc", ("", " ", "naïve café ☃"))),
        ("bool", (True, (False,))),
        ("None", (None, ())),
        ("Optional[int]", (1, (None, 0, -1, 2**31))),
        ("int | None", (1, (None, 0, -1, 2**31))),
        ("Union[str, bool]", ("abc", ("", " ", "naïve café ☃", True, False))),
        ("list[int]", ([1], ([],))),
        ("List[str]", (["abc"], ([],))),
        ("dict[str, int]", ({"abc": 1}, ({},))),
        ("list", ([], ())),
        ("'int'", (1, (0, -1, 2**31))),
    ],
)
def test_simple_annotations_have_typical_and_boundary_values(
    annotation: str, expected: tuple[object, tuple[object, ...]]
) -> None:
    assert values(annotation) == expected


@pytest.mark.parametrize(
    "annotation",
    [
        "Any",
        "tuple[int, str]",
        "set[int]",
        "bytes",
        "Path",
        "list[Path]",
        "Optional[Path]",
        "dict[list[int], int]",
        "Literal['a']",
        "Iterable[int]",
    ],
)
def test_other_annotations_have_none(annotation: str) -> None:
    assert values(annotation) is None


def test_each_case_changes_one_parameter_round_robin() -> None:
    source = "def f(count: int, name: str) -> str:\n    return name * count\n"

    cases = boundary_cases(function(source), [], limit=6)

    assert calls(cases) == [
        (("0", "'abc'"), {}),
        (("1", "''"), {}),
        (("-1", "'abc'"), {}),
        (("1", "' '"), {}),
        (("2147483648", "'abc'"), {}),
        (("1", "'naïve café ☃'"), {}),
    ]
    assert [case.rationale for case in cases[:2]] == [
        "boundary value for count",
        "boundary value for name",
    ]


def test_the_limit_bounds_the_cases_and_zero_turns_them_off() -> None:
    source = "def f(count: int, name: str):\n    pass\n"

    assert len(boundary_cases(function(source), [], limit=2)) == 2
    assert boundary_cases(function(source), [], limit=0) == ()


def test_an_unannotated_required_parameter_gives_no_cases() -> None:
    source = "def f(count: int, name):\n    pass\n"

    assert boundary_cases(function(source), [], limit=6) == ()


def test_unannotated_or_complex_optional_parameters_keep_their_default() -> None:
    source = (
        "def f(count: int, sep=',', *, path: Path = None, strict: bool = False):\n"
        "    pass\n"
    )

    cases = boundary_cases(function(source), [], limit=10)

    assert calls(cases) == [
        (("0",), {}),
        (("1",), {"strict": "False"}),
        (("-1",), {}),
        (("2147483648",), {}),
    ]


def test_keyword_only_required_parameters_are_passed_by_name() -> None:
    source = "def f(*, flag: bool):\n    pass\n"

    assert calls(boundary_cases(function(source), [], limit=6)) == [
        ((), {"flag": "False"})
    ]


def test_a_case_the_llm_already_proposed_is_dropped() -> None:
    source = "def f(count: int):\n    pass\n"
    llm = [Case(("0",)), Case(("-1",), {}, "llm")]

    cases = boundary_cases(function(source), llm, limit=6)

    assert calls(cases) == [(("2147483648",), {})]
    ids = {finding_id("app/m.py::f", case) for case in llm}
    assert not ids & {finding_id("app/m.py::f", case) for case in cases}


def test_method_cases_reuse_the_first_llm_constructor_arguments() -> None:
    source = "def add(self, amount: int) -> None:\n    self.total += amount\n"
    method = function(source, "method", "Account.add")
    llm = [Case(("5",), {}, "", ("100",), {"limit": "3"})]

    cases = boundary_cases(method, llm, limit=2)

    assert [(c.args, c.init_args, dict(c.init_kwargs)) for c in cases] == [
        (("0",), ("100",), {"limit": "3"}),
        (("-1",), ("100",), {"limit": "3"}),
    ]


def test_a_method_without_llm_cases_gets_none() -> None:
    source = "def add(self, amount: int) -> None:\n    pass\n"

    assert boundary_cases(function(source, "method", "Account.add"), [], 6) == ()


def test_a_constructor_gets_no_boundary_cases() -> None:
    source = "def __init__(self, amount: int) -> None:\n    self.amount = amount\n"
    constructor = function(source, "method", "Account.__init__")
    llm = [Case((), {}, "", ("1",), {})]

    assert boundary_cases(constructor, llm, 6) == ()


def test_class_methods_skip_cls_and_async_functions_are_handled() -> None:
    source = "@classmethod\nasync def make(cls, size: int):\n    pass\n"

    cases = boundary_cases(function(source, "classmethod", "Box.make"), [], 1)

    assert calls(cases) == [(("0",), {})]


def test_a_function_without_parameters_gets_none() -> None:
    assert boundary_cases(function("def f():\n    return 1\n"), [], 6) == ()


def test_every_built_value_is_among_the_boundary_values() -> None:
    from didibreak.boundary import boundary_values

    allowed = boundary_values()
    source = (
        "def f(a: int, b: float, c: str, d: bool, e: list[str], g: dict[str, int],"
        " h: int | None = None):\n    pass\n"
    )
    for case in boundary_cases(function(source), [], limit=20):
        for text in [*case.args, *case.kwargs.values()]:
            assert ast.literal_eval(text) in allowed
    assert ("δ", 0j) not in allowed
