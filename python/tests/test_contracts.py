"""contracts.py: inputs that contradict simple type annotations (task 21a)."""

import ast

import pytest

from didibreak.contracts import contradicts_annotations, value_matches


def annotation(text: str) -> ast.expr:
    return ast.parse(text, mode="eval").body


@pytest.mark.parametrize(
    ("text", "value", "expected"),
    [
        ("int", 3, True),
        ("int", True, True),
        ("int", 3.0, False),
        ("int", "3", False),
        ("float", 3, True),
        ("float", "3.0", False),
        ("complex", 1.5, True),
        ("str", b"x", False),
        ("bytes", "x", False),
        ("None", None, True),
        ("None", 0, False),
        ("object", [1], True),
        ("typing.Any", b"x", True),
        ("Optional[int]", None, True),
        ("Optional[int]", "1", False),
        ("Union[int, str]", "a", True),
        ("Union[int, str]", [1], False),
        ("int | None", 2.5, False),
        ("str | Path", 5, None),
        ("list", (1,), False),
        ("list[int]", [1, 2], True),
        ("list[int]", [1, "2"], False),
        ("List[str]", ["a"], True),
        ("set[int]", {1}, True),
        ("dict[str, int]", {"a": 1}, True),
        ("dict[str, int]", {1: 1}, False),
        ("Dict[str, Any]", {"a": object}, True),
        ("tuple[int, ...]", (1, 2, 3), True),
        ("tuple[int, ...]", (1, "x"), False),
        ("tuple[int, str]", (1, "x"), True),
        ("tuple[int, str]", (1,), False),
        ("'int'", "x", False),
        ("Iterable[int]", "x", None),
        ("NumberOrString", [1], None),
        ("Literal['a']", "b", None),
        ("list[Path]", [1], None),
    ],
)
def test_simple_annotations_are_judged_and_others_are_unknown(
    text: str, value: object, expected: bool | None
) -> None:
    assert value_matches(value, annotation(text)) is expected


SOURCE = '''
@decorator
def ordinal(value: int | str, gender: str = "male", *rest: int, **extra: bool) -> str:
    """Doc."""
    return str(value)
'''


@pytest.mark.parametrize(
    ("args", "kwargs", "expected"),
    [
        ([1], {}, False),
        (["1,000"], {"gender": "female"}, False),
        ([[1, 2]], {}, True),
        ([1, 2], {}, True),
        ([1, "x", 3, 4], {}, False),
        ([1, "x", "3"], {}, True),
        ([1], {"flag": True}, False),
        ([1], {"flag": 1}, True),
        ([1], {"flag": "yes"}, True),
        ([b"1"], {}, True),
    ],
)
def test_inputs_are_bound_to_parameters(
    args: list[object], kwargs: dict[str, object], expected: bool
) -> None:
    assert contradicts_annotations(SOURCE, args, kwargs) is expected


def test_functions_without_annotations_are_never_contradicted() -> None:
    source = "def f(a, b=1, *args, **kwargs):\n    return a\n"

    assert contradicts_annotations(source, [b"x", None, 3], {"z": []}) is False


def test_class_methods_skip_cls() -> None:
    source = "@classmethod\ndef make(cls, size: int) -> 'C':\n    return cls()\n"

    assert contradicts_annotations(source, ["big"], {}, skip_first=True) is True
    assert contradicts_annotations(source, [3], {}, skip_first=True) is False


def test_positional_only_parameters_are_not_bound_by_name() -> None:
    source = "def f(a: int, /, b: str = '') -> None:\n    pass\n"

    assert contradicts_annotations(source, [], {"a": "x"}) is False
    assert contradicts_annotations(source, [1], {"b": 2}) is True


def test_unbindable_or_unparsable_input_is_not_judged() -> None:
    source = "def f(a: int) -> None:\n    pass\n"

    assert contradicts_annotations(source, [1, "extra"], {"nope": "x"}) is False
    assert contradicts_annotations("def broken(:\n", ["x"], {}) is False
