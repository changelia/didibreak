import collections
import enum
import math

import pytest

from didibreak._harness_child import normalize
from didibreak.compare import (
    FLOAT_ABSOLUTE_TOLERANCE,
    FLOAT_RELATIVE_TOLERANCE,
    floats_close,
    values_equal,
)


def same(before: object, after: object) -> bool:
    left, right = normalize(before), normalize(after)
    assert left is not None and right is not None
    return values_equal(left, right)


def test_tolerances_are_the_spec_values() -> None:
    assert (FLOAT_RELATIVE_TOLERANCE, FLOAT_ABSOLUTE_TOLERANCE) == (1e-9, 1e-12)


def test_floats_within_tolerance_are_equal() -> None:
    assert floats_close(0.1 + 0.2, 0.3)
    assert floats_close(1e-13, 0.0)  # absolute tolerance near zero
    assert floats_close(math.nan, math.nan)
    assert floats_close(math.inf, math.inf)


def test_floats_outside_tolerance_differ() -> None:
    assert not floats_close(11.86, 11.9)
    assert not floats_close(1.0, 1.0 + 1e-8)
    assert not floats_close(math.inf, -math.inf)
    assert not floats_close(math.nan, 0.0)


def test_float_tolerance_applies_inside_containers() -> None:
    assert same([0.1 + 0.2], [0.3])
    assert same({"k": (0.1 + 0.2,)}, {"k": (0.3,)})
    assert not same([11.86], [11.9])


def test_scalars_compare_by_value_and_type() -> None:
    assert same("a", "a")
    assert not same("a", "b")
    assert not same(1, 1.0)
    assert not same(1, True)
    assert not same(None, 0)
    assert not same(b"a", "a")


def test_containers_compare_kind_length_and_order() -> None:
    assert same({1, 2}, {2, 1})
    assert same({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert not same([1, 2], [2, 1])
    assert not same([1, 2], (1, 2))
    assert not same([1], [1, 1])
    assert not same({"a": 1}, {"a": 2})
    assert not same({"a": 1}, {"b": 1})


Pair = collections.namedtuple("Pair", "left right")


class Shape(enum.Enum):
    CIRCLE = 1
    SQUARE = 2


def test_subclasses_and_enums_compare_class_and_value() -> None:
    assert same(Pair(1, 2), Pair(1, 2))
    assert not same(Pair(1, 2), Pair(1, 3))
    assert not same(Pair(1, 2), (1, 2))
    assert same(Shape.CIRCLE, Shape.CIRCLE)
    assert not same(Shape.CIRCLE, Shape.SQUARE)


@pytest.mark.parametrize("value", [[], {}, set(), (), ""])
def test_empty_values_equal_themselves(value: object) -> None:
    assert same(value, value)
