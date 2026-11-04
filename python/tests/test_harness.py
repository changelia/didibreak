import shutil
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fixture_repos import FIXTURES_DIR, load_expected

from didibreak import harness
from didibreak.harness import (
    PROCESS_EXITED_TYPE,
    Case,
    HarnessSettings,
    Outcome,
    Target,
    run_cases,
)

SETTINGS = HarnessSettings(python=sys.executable, timeout=5.0)


def make_tree(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return root


def target(tree: Path, module: str = "mod", qualname: str = "f") -> Target:
    return Target(tree=tree, import_root=tree, module=module, qualname=qualname)


def report_shape(outcome: Outcome) -> dict[str, str]:
    return {"kind": outcome.kind, "type_name": outcome.type_name, "repr": outcome.repr}


@pytest.mark.parametrize("version", ["before", "after"])
def test_outcomes_match_the_phone_fixture(version: str, tmp_path: Path) -> None:
    expected = load_expected("phone_regression")["findings"]
    tree = tmp_path / version
    shutil.copytree(
        FIXTURES_DIR / "phone_regression" / version,
        tree,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    cases = [Case(tuple(finding["args"])) for finding in expected]
    function = target(tree, "app.utils.phone", "normalize_phone")

    result = run_cases(function, cases, SETTINGS)

    assert result.skip_reason is None
    assert [report_shape(o) for o in result.outcomes] == [f[version] for f in expected]
    assert not list(tree.rglob("__pycache__"))  # nothing written into the tree


def test_each_tree_imports_only_its_own_version(tmp_path: Path) -> None:
    base = make_tree(tmp_path / "base", {"mod.py": "def f():\n    return 'base'\n"})
    current = make_tree(
        tmp_path / "current", {"mod.py": "def f():\n    return 'current'\n"}
    )
    # PYTHONPATH points at the other tree; it must not be used.
    leaky = {"PYTHONPATH": str(current), "PATH": "/usr/bin:/bin"}

    from_base = run_cases(target(base), [Case(())], SETTINGS, environment=leaky)
    from_current = run_cases(target(current), [Case(())], SETTINGS, environment=leaky)

    assert from_base.outcomes[0].repr == "'base'"
    assert from_current.outcomes[0].repr == "'current'"


def test_module_found_outside_the_tree_is_skipped(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "tree", {"other.py": ""})

    result = run_cases(target(tree, "json", "dumps"), [Case(("1",))], SETTINGS)

    assert result == harness.HarnessResult((), "import resolved outside tree")


def test_tree_wins_over_an_editable_install(tmp_path: Path) -> None:
    # The test interpreter has didibreak installed in editable mode (.pth).
    tree = make_tree(
        tmp_path / "tree", {"didibreak/__init__.py": "def f():\n    return 'tree'\n"}
    )
    elsewhere = make_tree(tmp_path / "empty", {"other.py": ""})

    inside = run_cases(target(tree, "didibreak"), [Case(())], SETTINGS)
    outside = run_cases(target(elsewhere, "didibreak", "main"), [Case(())], SETTINGS)

    assert inside.outcomes[0].repr == "'tree'"
    assert outside.skip_reason == "import resolved outside tree"


def test_import_errors_and_missing_functions_are_skip_reasons(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "tree", {"broken.py": "1 / 0\n", "mod.py": "x = 1\n"})

    broken = run_cases(target(tree, "broken"), [Case(())], SETTINGS)
    missing = run_cases(target(tree, "mod", "g"), [Case(())], SETTINGS)
    not_callable = run_cases(target(tree, "mod", "x"), [Case(())], SETTINGS)

    assert broken.skip_reason == "import failed: ZeroDivisionError"
    assert missing.skip_reason == "function not found after import"
    assert not_callable.skip_reason == "function not found after import"


def test_methods_are_found_by_qualified_name(tmp_path: Path) -> None:
    source = "class C:\n    @staticmethod\n    def f(x):\n        return 2 * x\n"
    tree = make_tree(tmp_path / "tree", {"mod.py": source})

    result = run_cases(target(tree, "mod", "C.f"), [Case(("21",))], SETTINGS)

    assert result.outcomes[0].value == {"type": "int", "value": 42}


def test_exceptions_and_keyword_arguments_are_recorded(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path / "tree", {"mod.py": "def f(a, *, b):\n    return a[b]\n"}
    )
    cases = [Case(("[1]",), {"b": "0"}), Case(("[]",), {"b": "0"})]

    first, second = run_cases(target(tree), cases, SETTINGS).outcomes

    assert first.value == {"type": "int", "value": 1}
    assert (second.kind, second.type_name) == ("exception", "builtins.IndexError")
    assert second.message == "list index out of range"


def test_a_hanging_case_does_not_stop_the_others(tmp_path: Path) -> None:
    source = "import time\ndef f(n):\n    if n:\n        time.sleep(60)\n    return n\n"
    tree = make_tree(tmp_path / "tree", {"mod.py": source})
    settings = HarnessSettings(python=sys.executable, timeout=0.5)

    start = time.monotonic()
    outcomes = run_cases(target(tree), [Case(("1",)), Case(("0",))], settings).outcomes

    assert [o.kind for o in outcomes] == ["timeout", "return"]
    assert outcomes[0].repr == "<timed out after 0.5 s>"
    assert time.monotonic() - start < 10


def test_child_ignoring_its_timeout_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "_KILL_GRACE_SECONDS", 1.0)
    source = """\
        import time
        def f():
            while True:
                try:
                    time.sleep(60)
                except BaseException:
                    pass
        """
    tree = make_tree(tmp_path / "tree", {"mod.py": source})
    settings = HarnessSettings(python=sys.executable, timeout=0.2)

    outcomes = run_cases(target(tree), [Case(()), Case(())], settings).outcomes

    assert [o.kind for o in outcomes] == ["timeout", "timeout"]


def test_import_that_hangs_is_a_skip_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "_KILL_GRACE_SECONDS", 1.0)
    tree = make_tree(tmp_path / "tree", {"mod.py": "import time\ntime.sleep(60)\n"})
    settings = HarnessSettings(python=sys.executable, timeout=0.2)

    result = run_cases(target(tree), [Case(())], settings)

    assert result.skip_reason == "import timed out"


def test_a_crashing_case_is_recorded_and_later_cases_still_run(tmp_path: Path) -> None:
    source = "import os\ndef f(n):\n    if n:\n        os._exit(3)\n    return n\n"
    tree = make_tree(tmp_path / "tree", {"mod.py": source})
    cases = [Case(("0",)), Case(("1",)), Case(("0",))]

    outcomes = run_cases(target(tree), cases, SETTINGS).outcomes

    assert [o.kind for o in outcomes] == ["return", "exception", "return"]
    assert outcomes[1].type_name == PROCESS_EXITED_TYPE
    assert outcomes[1].message == "the process exited with code 3 during the case"


def test_output_and_exit_calls_of_the_function_are_contained(tmp_path: Path) -> None:
    source = """\
        import sys
        def f():
            print('{"kind": "return"}')
            print("noise", file=sys.stderr)
            sys.exit(4)
        """
    tree = make_tree(tmp_path / "tree", {"mod.py": source})

    (outcome,) = run_cases(target(tree), [Case(())], SETTINGS).outcomes

    assert (outcome.kind, outcome.type_name) == ("exception", "builtins.SystemExit")


def test_working_directory_is_a_temporary_folder(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path / "tree", {"mod.py": "import os\ndef f():\n    return os.getcwd()\n"}
    )

    (outcome,) = run_cases(target(tree), [Case(())], SETTINGS).outcomes

    assert outcome.value is not None
    assert not Path(outcome.value["value"]).resolve().is_relative_to(tmp_path.resolve())


def test_arguments_must_be_python_literals(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "tree", {"mod.py": "def f(x):\n    return x\n"})

    with pytest.raises(ValueError, match=r"not a Python literal: .__import__"):
        run_cases(target(tree), [Case(("__import__('os')",))], SETTINGS)


def test_no_pickle_crosses_the_process_boundary() -> None:
    sources = [Path(harness.__file__), Path(harness._CHILD_SCRIPT)]
    for path in sources:
        assert "import pickle" not in path.read_text(encoding="utf-8")


def test_partial_last_line_of_a_killed_child_is_ignored(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text('{"ready": true}\n{"kind": "ret', encoding="utf-8")

    assert harness._read_records(results) == [{"ready": True}]
