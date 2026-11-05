import sys
from pathlib import Path

from conftest import GitRepository

from didibreak.cli import load_source_files
from didibreak.functions import detect_changed_functions
from didibreak.gitdiff import changed_python_files, resolve_base
from didibreak.harness import Case, HarnessSettings
from didibreak.pipeline import NO_CASES_REASON, UNLABELLED, Analysis, analyze

SETTINGS = HarnessSettings(python=sys.executable, timeout=5.0)


def run(root: Path, cases: dict[str, tuple[Case, ...]]) -> Analysis:
    base = resolve_base(root, "HEAD")
    files = changed_python_files(root, base)
    detection = detect_changed_functions(load_source_files(root, base, files), 10)
    base_paths = {item.path: item.old_path for item in files.changed if item.old_path}
    return analyze(root, base, detection.functions, base_paths, cases, SETTINGS)


def test_both_versions_run_outside_the_working_tree(
    git_repository: GitRepository,
) -> None:
    git_repository.write("app.py", "def where():\n    return __file__\n")
    git_repository.commit()
    git_repository.write("app.py", "def where():\n    return str(__file__)\n")
    root = git_repository.path
    status = git_repository.status()

    analysis = run(root, {"app.py::where": (Case(()),)})

    (finding,) = analysis.findings  # the two temporary paths differ
    assert finding.before is not None
    for outcome in (finding.before, finding.after):
        assert outcome.repr.endswith("/tree/app.py'")
        assert str(root.resolve()) not in outcome.repr
    assert git_repository.status() == status
    assert not list(root.rglob("__pycache__"))


def test_unlabelled_findings_are_unclear_and_new_functions_keep_their_label(
    git_repository: GitRepository,
) -> None:
    git_repository.write("m.py", "def f(x):\n    return x\n")
    git_repository.commit()
    git_repository.write(
        "m.py", "def f(x):\n    return x + 1\n\ndef g(x):\n    return 1 / x\n"
    )

    analysis = run(
        git_repository.path,
        {"m.py::f": (Case(("1",)),), "m.py::g": (Case(("0",)), Case(("1",)))},
    )

    assert [(f.function, f.label) for f in analysis.findings] == [
        ("m.py::f", UNLABELLED),
        ("m.py::g", "new_function"),
    ]
    assert analysis.cases_run == 3
    assert [f.report_name for f in analysis.checked] == ["m.py::f", "m.py::g"]


def test_renamed_file_runs_the_base_version_from_the_old_path(
    git_repository: GitRepository,
) -> None:
    # Enough unchanged lines for git to see a rename, not a delete and an add.
    unchanged = "".join(f"def helper_{n}():\n    return {n}\n\n" for n in range(8))
    git_repository.write("old_name.py", unchanged + "def f():\n    return 1\n")
    git_repository.commit()
    git_repository.git("mv", "old_name.py", "new_name.py")
    git_repository.write("new_name.py", unchanged + "def f():\n    return 2\n")

    analysis = run(git_repository.path, {"new_name.py::f": (Case(()),)})

    (finding,) = analysis.findings
    assert finding.before is not None
    assert (finding.before.repr, finding.after.repr) == ("1", "2")


def test_functions_without_cases_or_failing_imports_are_skipped(
    git_repository: GitRepository,
) -> None:
    git_repository.write("a.py", "raise ImportError\n\ndef f():\n    return 1\n")
    git_repository.write("b.py", "def g():\n    return 1\n")
    git_repository.commit()
    git_repository.write("a.py", "def f():\n    return 2\n")
    git_repository.write("b.py", "def g():\n    return 2\n")

    analysis = run(git_repository.path, {"a.py::f": (Case(()),)})

    assert analysis.findings == ()
    assert [(f.report_name, f.skip_reason) for f in analysis.skipped] == [
        ("a.py::f", "import failed: ImportError (base version)"),
        ("b.py::g", NO_CASES_REASON),
    ]


def test_src_layout_imports_from_the_package_root(
    git_repository: GitRepository,
) -> None:
    git_repository.write("pkg/pyproject.toml", "[project]\nname = 'p'\n")
    git_repository.write("pkg/src/p/__init__.py", "")
    git_repository.write("pkg/src/p/core.py", "def f():\n    return __name__\n")
    git_repository.commit()
    git_repository.write("pkg/src/p/core.py", "def f():\n    return __name__ * 2\n")

    analysis = run(git_repository.path, {"pkg/src/p/core.py::f": (Case(()),)})

    (finding,) = analysis.findings
    assert finding.before is not None
    assert finding.before.repr == "'p.core'"
