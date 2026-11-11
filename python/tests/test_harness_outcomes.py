import collections
import dataclasses
import enum
import json
import math
from collections.abc import Iterator

import pytest

from didibreak._harness_child import (
    MESSAGE_LIMIT,
    REPR_LIMIT,
    exception_outcome,
    normalize,
    return_outcome,
    timeout_outcome,
    type_name,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, {"type": "none"}),
        (True, {"type": "bool", "value": True}),
        (7, {"type": "int", "value": 7}),
        ("é", {"type": "str", "value": "é"}),
        (b"\x00\xff", {"type": "bytes", "value": "00ff"}),
        (0.1, {"type": "float", "value": "0.1"}),
        (math.inf, {"type": "float", "value": "inf"}),
    ],
)
def test_scalars_are_tagged(value: object, expected: dict[str, object]) -> None:
    assert normalize(value) == expected


def test_bool_and_int_are_distinct() -> None:
    assert normalize(1) != normalize(True)


def test_nan_is_kept_as_a_comparable_float() -> None:
    assert normalize(math.nan) == normalize(float("nan"))


def test_list_and_tuple_are_tagged_and_ordered() -> None:
    assert normalize([1, "a"]) == {
        "type": "list",
        "items": [{"type": "int", "value": 1}, {"type": "str", "value": "a"}],
    }
    assert normalize((1,))["type"] == "tuple"  # type: ignore[index]


def test_sets_are_sorted_by_repr_so_order_does_not_matter() -> None:
    assert normalize({3, 1, 2}) == normalize({2, 3, 1})
    assert normalize(frozenset({"b", "a"})) == {
        "type": "frozenset",
        "items": [{"type": "str", "value": "a"}, {"type": "str", "value": "b"}],
    }


def test_dict_keys_are_sorted_by_repr() -> None:
    assert normalize({"b": 1, "a": 2}) == normalize({"a": 2, "b": 1})
    assert normalize({1: None}) == {
        "type": "dict",
        "items": [[{"type": "int", "value": 1}, {"type": "none"}]],
    }


def test_other_types_are_not_representable() -> None:
    @dataclasses.dataclass
    class Point:
        x: int

    assert normalize(object()) is None
    assert normalize(Point(1)) is None  # dataclasses: a v0.2 candidate
    assert normalize([1, object()]) is None


Pair = collections.namedtuple("Pair", "left right")


class Color(enum.IntEnum):
    RED = 1


class Mode(enum.StrEnum):
    FAST = "fast"


@pytest.mark.parametrize(
    ("value", "base_value"),
    [
        (Pair(1, 2), (1, 2)),
        (collections.OrderedDict(b=1, a=2), {"a": 2, "b": 1}),
        (collections.defaultdict(list, k=[1]), {"k": [1]}),
        (Color.RED, 1),
        (Mode.FAST, "fast"),
    ],
)
def test_subclasses_are_normalized_through_their_builtin_base(
    value: object, base_value: object
) -> None:
    normalized = normalize(value)
    expected = normalize(base_value)

    assert normalized is not None and expected is not None
    assert normalized == {**expected, "class": type_name(value)}


class Shape(enum.Enum):
    CIRCLE = object()
    SQUARE = object()


class Other(enum.Enum):
    CIRCLE = 1


def test_enum_members_are_compared_by_class_and_name() -> None:
    assert normalize(Shape.CIRCLE) == {
        "type": "enum",
        "class": type_name(Shape.CIRCLE),
        "name": "CIRCLE",
    }
    assert normalize(Shape.CIRCLE) != normalize(Shape.SQUARE)
    assert normalize(Shape.CIRCLE) != normalize(Other.CIRCLE)
    assert normalize({Shape.SQUARE: [Shape.CIRCLE]}) is not None


def test_int_and_str_enums_use_their_builtin_base_not_the_enum_rule() -> None:
    normalized = normalize(Color.RED)

    assert normalized is not None
    assert normalized["type"] == "int"


def test_subclass_class_is_kept_in_nested_values() -> None:
    normalized = normalize([Pair(1, 2)])

    assert normalized is not None
    assert normalized["items"][0]["class"].endswith(".Pair")
    assert normalize([Pair(1, 2)]) != normalize([(1, 2)])


def test_overridden_methods_do_not_change_the_normalized_value() -> None:
    class Sneaky(list[object]):
        def __iter__(self) -> Iterator[object]:
            return iter(["changed"])

    normalized = normalize(Sneaky([1]))

    assert normalized is not None
    assert normalized["items"] == [{"type": "int", "value": 1}]


def test_cycles_huge_ints_and_huge_containers_are_not_representable() -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    assert normalize(cycle) is None
    assert normalize(10**5000) is None
    assert normalize(list(range(20_000))) is None


def test_normalized_values_survive_json() -> None:
    value = {"k": [1.5, b"x", {None}, (True,)], 2: "s"}
    normalized = normalize(value)
    assert json.loads(json.dumps(normalized)) == normalized


def test_return_outcome_has_type_repr_and_value() -> None:
    assert return_outcome("+995") == {
        "kind": "return",
        "type_name": "builtins.str",
        "repr": "'+995'",
        "value": {"type": "str", "value": "+995"},
    }


def test_return_outcome_without_value_when_not_representable() -> None:
    outcome = return_outcome(object())
    assert outcome["type_name"] == "builtins.object"
    assert "value" not in outcome


def test_repr_is_truncated_and_failing_repr_is_reported() -> None:
    class Broken:
        def __repr__(self) -> str:
            raise RuntimeError

    assert len(return_outcome("x" * 5000)["repr"]) == REPR_LIMIT
    assert return_outcome(Broken())["repr"] == "<repr failed: RuntimeError>"


def test_exception_outcome_has_qualified_type_and_truncated_message() -> None:
    outcome = exception_outcome(ValueError("m" * 900))
    assert outcome["kind"] == "exception"
    assert outcome["type_name"] == "builtins.ValueError"
    assert len(outcome["message"]) == MESSAGE_LIMIT
    assert "value" not in outcome


def test_timeout_outcome_matches_the_report_shape() -> None:
    assert timeout_outcome(10.0) == {
        "kind": "timeout",
        "type_name": "",
        "repr": "<timed out after 10 s>",
    }


class _ReprFails:
    def __repr__(self) -> str:
        raise RuntimeError("no repr")


@pytest.mark.parametrize(
    "value", [{_ReprFails(): 1}, {_ReprFails()}, frozenset({_ReprFails()})]
)
def test_a_raising_repr_inside_a_value_is_a_normal_return(value: object) -> None:
    # Audit 35a, finding 5: the error escaped and crashed the child process.
    outcome = return_outcome(value)

    assert outcome["kind"] == "return"
    assert outcome["type_name"] == type_name(value)
    assert outcome["repr"] == "<repr failed: RuntimeError>"
    assert "value" not in outcome
