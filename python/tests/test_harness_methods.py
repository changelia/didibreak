"""Instance methods in the harness: build, call, record the state (task 30)."""

import sys
import textwrap
from pathlib import Path

import pytest

from didibreak.harness import Case, HarnessSettings, Target, check_import, run_cases

SETTINGS = HarnessSettings(python=sys.executable, timeout=5.0)
SHORT = HarnessSettings(python=sys.executable, timeout=0.5)


def method_target(
    tree: Path, source: str, qualname: str, is_async: bool = False
) -> Target:
    (tree / "mod.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return Target(tree, tree, "mod", qualname, is_async=is_async, is_method=True)


def case(*args: str, init: tuple[str, ...] = (), **init_kwargs: str) -> Case:
    return Case(tuple(args), {}, "", init, init_kwargs)


ACCOUNT = """
    class Account:
        def __init__(self, balance, owner="ada"):
            self.balance = balance
            self.owner = owner

        def deposit(self, amount):
            if amount < 0:
                self.balance = -1
                raise ValueError("negative amount")
            self.balance += amount
    """


def state_of(outcome: object) -> dict[str, object]:
    items = outcome.state["items"]  # type: ignore[attr-defined]
    return {name["value"]: node for name, node in items}


def test_a_method_that_returns_none_records_the_state_after_the_call(
    tmp_path: Path,
) -> None:
    target = method_target(tmp_path, ACCOUNT, "Account.deposit")

    result = run_cases(target, [case("5", init=("100",))], SETTINGS)

    (outcome,) = result.outcomes
    assert (outcome.kind, outcome.repr, outcome.stable) == ("return", "None", True)
    assert outcome.state_repr == "{'balance': 105, 'owner': 'ada'}"
    assert state_of(outcome) == {
        "balance": {"type": "int", "value": 105},
        "owner": {"type": "str", "value": "ada"},
    }
    assert not outcome.construction_failed


def test_the_state_is_recorded_after_an_exception_too(tmp_path: Path) -> None:
    target = method_target(tmp_path, ACCOUNT, "Account.deposit")

    (outcome,) = run_cases(target, [case("-5", init=("100",))], SETTINGS).outcomes

    assert (outcome.kind, outcome.type_name) == ("exception", "builtins.ValueError")
    assert state_of(outcome)["balance"] == {"type": "int", "value": -1}


def test_constructor_keyword_arguments_are_passed(tmp_path: Path) -> None:
    target = method_target(tmp_path, ACCOUNT, "Account.deposit")

    (outcome,) = run_cases(
        target, [case("1", init=("0",), owner="'bob'")], SETTINGS
    ).outcomes

    assert outcome.state_repr == "{'balance': 1, 'owner': 'bob'}"


def test_slots_are_read_including_private_and_empty_ones(tmp_path: Path) -> None:
    source = """
        class Point:
            __slots__ = ("x", "__secret", "unset")

            def __init__(self, x):
                self.x = x
                self.__secret = x * 2

            def move(self, dx):
                self.x += dx
        """
    target = method_target(tmp_path, source, "Point.move")

    (outcome,) = run_cases(target, [case("1", init=("3",))], SETTINGS).outcomes

    assert outcome.state_repr == "{'_Point__secret': 6, 'x': 4}"


def test_a_dataclass_instance_is_built_from_its_fields(tmp_path: Path) -> None:
    source = """
        from dataclasses import dataclass, field

        @dataclass
        class Cart:
            owner: str
            items: list = field(default_factory=list)

            def add(self, item):
                self.items.append(item)
                return len(self.items)
        """
    target = method_target(tmp_path, source, "Cart.add")

    (outcome,) = run_cases(target, [case("'pen'", init=("'ada'",))], SETTINGS).outcomes

    assert outcome.repr == "1"
    assert outcome.state_repr == "{'items': ['pen'], 'owner': 'ada'}"


def test_an_attribute_that_cannot_be_normalized_is_compared_by_type(
    tmp_path: Path,
) -> None:
    source = """
        class Holder:
            def __init__(self):
                self.lock = object()

            def touch(self):
                return 1
        """
    target = method_target(tmp_path, source, "Holder.touch")

    (outcome,) = run_cases(target, [case()], SETTINGS).outcomes

    assert outcome.stable  # the address in the repr does not matter
    assert state_of(outcome) == {"lock": {"type": "opaque", "class": "builtins.object"}}


def test_a_state_that_changes_between_runs_is_flaky(tmp_path: Path) -> None:
    source = """
        import time

        class Stamp:
            def touch(self):
                self.at = time.perf_counter_ns()
        """
    target = method_target(tmp_path, source, "Stamp.touch")

    (outcome,) = run_cases(target, [case()], SETTINGS).outcomes

    assert not outcome.stable


def test_a_constructor_that_raises_marks_the_outcome(tmp_path: Path) -> None:
    source = """
        class Port:
            def __init__(self, number):
                if not 0 < number < 65536:
                    raise ValueError("out of range")
                self.number = number

            def text(self):
                return str(self.number)
        """
    target = method_target(tmp_path, source, "Port.text")

    failed, built = run_cases(
        target, [case(init=("0",)), case(init=("80",))], SETTINGS
    ).outcomes

    assert failed.construction_failed
    assert (failed.kind, failed.type_name) == ("exception", "builtins.ValueError")
    assert failed.state is None
    assert not built.construction_failed
    assert built.repr == "'80'"


def test_a_constructor_that_writes_outside_the_scratch_folder_is_blocked(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "marker"
    source = f"""
        class Logger:
            def __init__(self):
                open({str(marker)!r}, "w").write("x")

            def name(self):
                return "log"
        """
    target = method_target(tmp_path, source, "Logger.name")

    result = run_cases(target, [case()], SETTINGS)

    assert result.skip_reason == "blocked: open"
    assert not marker.exists()


def test_a_constructor_that_never_ends_times_out(tmp_path: Path) -> None:
    source = """
        class Spin:
            def __init__(self, x):
                while x:
                    pass

            def value(self):
                return 1
        """
    target = method_target(tmp_path, source, "Spin.value")

    first, second = run_cases(
        target, [case(init=("1",)), case(init=("0",))], SHORT
    ).outcomes

    assert first.kind == "timeout"
    assert (second.kind, second.repr) == ("return", "1")


def test_an_async_method_is_awaited_and_its_state_recorded(tmp_path: Path) -> None:
    source = """
        import asyncio

        class Counter:
            def __init__(self):
                self.count = 0

            async def bump(self, by):
                await asyncio.sleep(0)
                self.count += by
                return self.count
        """
    target = method_target(tmp_path, source, "Counter.bump", is_async=True)

    (outcome,) = run_cases(target, [case("2")], SETTINGS).outcomes

    assert outcome.repr == "2"
    assert outcome.state_repr == "{'count': 2}"


@pytest.mark.parametrize("qualname", ["Account.missing", "helper.method"])
def test_a_method_that_cannot_be_found_is_reported(
    tmp_path: Path, qualname: str
) -> None:
    source = (
        textwrap.dedent(ACCOUNT)
        + "\n\ndef helper():\n    return 1\n\n\nhelper.method = print\n"
    )
    target = method_target(tmp_path, source, qualname)

    assert check_import(target, SETTINGS) == "function not found after import"


def test_what_the_constructor_did_is_recorded_before_the_method_runs(
    tmp_path: Path,
) -> None:
    target = method_target(tmp_path, ACCOUNT, "Account.deposit")

    (outcome,) = run_cases(target, [case("5", init=("100",))], SETTINGS).outcomes

    built = outcome.construction
    assert built is not None
    assert (built.kind, built.type_name) == ("return", "mod.Account")
    assert built.state_repr == "{'balance': 100, 'owner': 'ada'}"
    assert outcome.state_repr == "{'balance': 105, 'owner': 'ada'}"


def test_a_failed_constructor_records_no_construction(tmp_path: Path) -> None:
    source = """
        class Port:
            def __init__(self, number):
                raise ValueError(number)

            def text(self):
                return ""
        """
    target = method_target(tmp_path, source, "Port.text")

    (outcome,) = run_cases(target, [case(init=("0",))], SETTINGS).outcomes

    assert outcome.construction_failed
    assert outcome.construction is None


def test_a_constructor_state_that_changes_between_runs_is_flaky(
    tmp_path: Path,
) -> None:
    source = """
        import time

        class Stamp:
            def __init__(self):
                self.at = time.perf_counter_ns()

            def reset(self):
                self.at = 0
        """
    target = method_target(tmp_path, source, "Stamp.reset")

    (outcome,) = run_cases(target, [case()], SETTINGS).outcomes

    assert outcome.state_repr == "{'at': 0}"
    assert not outcome.stable


def test_for_the_constructor_itself_the_construction_is_the_outcome(
    tmp_path: Path,
) -> None:
    target = method_target(tmp_path, ACCOUNT, "Account.__init__")

    built, failed = run_cases(
        target, [case(init=("7",)), case(init=())], SETTINGS
    ).outcomes

    assert (built.kind, built.type_name) == ("return", "mod.Account")
    assert built.state_repr == "{'balance': 7, 'owner': 'ada'}"
    assert failed.construction_failed
    assert failed.type_name == "builtins.TypeError"
