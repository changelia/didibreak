"""scripts/evaluate.py: plan checks, budget, summary and a local run (task 21)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evaluate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluate = load_script()


def write_plan(folder: Path, scenarios: list[dict[str, str]], **extra: object) -> Path:
    plan = {
        "budget": 1.0,
        "max_cost_per_run": 0.1,
        "repos": {"lib": {"url": "https://example.invalid/lib"}},
        "scenarios": scenarios,
        **extra,
    }
    path = folder / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def scenario(**fields: str) -> dict[str, str]:
    base = {"id": "s1", "repo": "lib", "kind": "replay", "commit": "abc", "intent": "i"}
    return {**base, **fields}


def test_plan_is_loaded_with_scenarios_and_extra_spend(tmp_path: Path) -> None:
    path = write_plan(tmp_path, [scenario()], extra_spent=0.25)

    plan = evaluate.load_plan(path)

    assert plan.budget == 1.0
    assert plan.extra_spent == 0.25
    assert plan.scenarios[0].kind == "replay"
    assert plan.setup == {"lib": {}}


@pytest.mark.parametrize(
    ("scenarios", "message"),
    [
        ([scenario(kind="sideways")], "unknown kind"),
        ([scenario(repo="other")], "unknown repository"),
        ([scenario(), scenario()], "duplicate scenario id"),
        ([scenario(kind="seeded")], "needs a patch"),
    ],
)
def test_invalid_plans_are_rejected(
    tmp_path: Path, scenarios: list[dict[str, str]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        evaluate.load_plan(write_plan(tmp_path, scenarios))


@pytest.mark.parametrize(
    ("spent", "allowed"), [(0.0, True), (0.9, True), (0.95, False)]
)
def test_a_run_is_allowed_only_if_its_worst_case_fits(
    spent: float, allowed: bool
) -> None:
    assert evaluate.can_afford(spent, 0.1, 1.0) is allowed


def test_run_cost_is_zero_without_a_report_or_price() -> None:
    assert evaluate.run_cost({"report": None}) == 0.0
    assert evaluate.run_cost({"report": {"usage": {"cost_usd": None}}}) == 0.0
    assert evaluate.run_cost({"report": {"usage": {"cost_usd": 0.5}}}) == 0.5


@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("obvious I/O: open", "obvious I/O"),
        ("import failed: ModuleNotFoundError (base version)", "import failed"),
        ("instance method", "instance method"),
    ],
)
def test_skip_reasons_are_grouped(reason: str, category: str) -> None:
    assert evaluate.skip_category(reason) == category


def test_precision_is_none_without_labelled_findings() -> None:
    assert evaluate.precision(0, 0) is None
    assert evaluate.precision(7, 10) == 0.7


def finding(identifier: str, label: str) -> dict[str, object]:
    return {"id": identifier, "label": label}


def test_summary_counts_labels_precision_and_skips(tmp_path: Path) -> None:
    plan = write_plan(tmp_path, [scenario()])
    (tmp_path / "reports").mkdir()
    report = {
        "findings": [
            finding("a", "unexpected"),
            finding("b", "unexpected"),
            finding("c", "unexpected"),
            finding("d", "expected"),
        ],
        "summary": {
            "functions_checked": 2,
            "skipped": [{"function": "m.py::f", "reason": "obvious I/O: open"}],
        },
        "usage": {"cost_usd": 0.01},
    }
    (tmp_path / "reports" / "s1.json").write_text(json.dumps({"report": report}))
    labels = {"s1/a": {"real": True}, "s1/b": {"real": False}}
    (tmp_path / "labels.json").write_text(json.dumps(labels))

    summary = evaluate.summarize(plan)

    assert "| lib | 1 | 2 | 1 | 3 / 0 / 1 / 0 | 1 / 2 | 50% | $0.0100 |" in summary
    assert "| obvious I/O | 1 |" in summary
    assert "Unlabelled unexpected findings: s1/c" in summary


def git(folder: Path, *arguments: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(folder),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            *arguments,
        ],
        check=True,
        capture_output=True,
    )


def test_replay_runs_check_on_the_reverted_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = tmp_path / "repos" / "lib"
    clone.mkdir(parents=True)
    git(clone, "init", "-q")
    (clone / "lib.py").write_text("def f(x):\n    return x\n")
    git(clone, "add", ".")
    git(clone, "commit", "-qm", "first")
    (clone / "lib.py").write_text("def f(x):\n    return x + 1\n")
    git(clone, "commit", "-qam", "fix")
    plan = write_plan(tmp_path, [scenario(commit="HEAD")])
    seen: dict[str, str] = {}
    real_run = subprocess.run

    def fake_run(
        command: list[str], **options: object
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            return real_run(command, **options)  # type: ignore[call-overload]
        seen["source"] = (Path(str(options["cwd"])) / "lib.py").read_text()
        reply = {"findings": [], "summary": {}, "usage": {"cost_usd": 0.0}}
        return subprocess.CompletedProcess(command, 0, json.dumps(reply), "")

    monkeypatch.setattr(evaluate.subprocess, "run", fake_run)

    assert evaluate.run(plan, tmp_path / "repos", Path(sys.executable)) == 0

    assert seen["source"] == "def f(x):\n    return x\n"
    saved = json.loads((tmp_path / "reports" / "s1.json").read_text())
    assert saved["exit_code"] == 0
    assert "<python>" in saved["command"]
    assert str(tmp_path) not in json.dumps(saved["command"])


def test_run_stops_before_the_budget_is_exceeded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = write_plan(tmp_path, [scenario()], extra_spent=0.95)

    assert evaluate.run(plan, tmp_path / "repos", Path(sys.executable)) == 1

    assert "stopping before s1" in capsys.readouterr().out
