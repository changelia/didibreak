import subprocess
import sys

from didibreak.compare import FINDING_ID_LENGTH, finding_id
from didibreak.harness import Case

PHONE = "app/utils/phone.py::normalize_phone"


def test_id_is_twelve_lowercase_hex_characters() -> None:
    identifier = finding_id(PHONE, Case(("'995 555 12 34 56'",)))

    assert len(identifier) == FINDING_ID_LENGTH == 12
    assert set(identifier) <= set("0123456789abcdef")


def test_id_is_a_fixed_value() -> None:
    # Regression guard: the id must never change between versions and
    # machines for the same function and arguments.
    assert finding_id(PHONE, Case(("'995 555 12 34 56'",))) == "30040f8bc543"


def test_spelling_and_keyword_order_do_not_change_the_id() -> None:
    first = Case(("'a'",), {"x": "1", "y": "[1, 2]"})
    second = Case(('"a"',), {"y": "[1,2]", "x": "1"})

    assert finding_id(PHONE, first) == finding_id(PHONE, second)


def test_function_and_arguments_change_the_id() -> None:
    case = Case(("1",))

    assert finding_id(PHONE, case) != finding_id("other.py::f", case)
    assert finding_id(PHONE, case) != finding_id(PHONE, Case(("2",)))
    assert finding_id(PHONE, case) != finding_id(PHONE, Case(("1.0",)))
    assert finding_id(PHONE, case) != finding_id(PHONE, Case((), {"x": "1"}))


def test_id_does_not_depend_on_the_hash_seed() -> None:
    code = (
        "from didibreak.compare import finding_id;"
        "from didibreak.harness import Case;"
        "print(finding_id('m.py::f', Case((\"{'a', 'b', 'c', 'd'}\",))))"
    )
    ids = {
        subprocess.run(
            [sys.executable, "-c", code],
            env={"PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2", "3")
    }

    assert len(ids) == 1
