"""Run the real-repository evaluation and summarize its labelled results (task 21).

From python/, with OPENAI_API_KEY set and the repositories cloned:

    uv run python scripts/evaluate.py run PLAN REPOS PYTHON
    uv run python scripts/evaluate.py summarize PLAN
    uv run python scripts/evaluate.py copy-time REPO [REPO ...]

PLAN is ``evaluation/plan.json``: the repositories and the scenarios. Each
scenario builds a working tree in a temporary git worktree of a cloned
repository (REPOS holds one clone per repository, named by its key) and runs
``didibreak check --format json`` there with PYTHON as ``--python``:

- ``replay``: the tree is at ``commit`` and the commit's diff is applied in
  reverse, so the bug it fixed comes back as an uncommitted change.
- ``forward``: the tree is at the commit's parent and the diff is applied.
- ``seeded``: the tree is at ``commit`` and ``patch`` (relative to PLAN) is
  applied.

A repository's ``setup`` files are committed on top of the scenario's base
first (for example a generated ``_version.py`` that git ignores). Reports
are saved next to PLAN in ``reports/<id>.json``; a scenario with a saved
report is not run again. Before each run the total cost of all saved
reports, ``extra_spent`` (spend not in any report) and
``max_cost_per_run`` must stay within ``budget``, otherwise the
run stops. ``summarize`` combines the reports with the hand labels in
``labels.json`` and prints Markdown tables. The API key is never written.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCENARIO_KINDS = ("replay", "forward", "seeded")
GIT_IDENTITY = ("-c", "user.name=didibreak-eval", "-c", "user.email=eval@invalid")


@dataclass(frozen=True)
class Scenario:
    """One ``didibreak check`` run on a prepared working tree."""

    id: str
    repo: str
    kind: str
    commit: str
    intent: str
    patch: str | None = None


@dataclass(frozen=True)
class Plan:
    """Repositories, scenarios and cost limits of the evaluation."""

    budget: float
    max_cost_per_run: float
    extra_spent: float
    setup: Mapping[str, Mapping[str, str]]
    scenarios: tuple[Scenario, ...]


def load_plan(path: Path) -> Plan:
    """Read and check ``plan.json``.

    Args:
        path: The plan file.

    Returns:
        The plan.

    Raises:
        ValueError: If a scenario has an unknown kind or repository, a
            duplicate id, or a seeded scenario has no patch.
    """
    data = json.loads(path.read_text())
    repos = data["repos"]
    scenarios = []
    seen: set[str] = set()
    for item in data["scenarios"]:
        scenario = Scenario(
            id=item["id"],
            repo=item["repo"],
            kind=item["kind"],
            commit=item["commit"],
            intent=item["intent"],
            patch=item.get("patch"),
        )
        if scenario.kind not in SCENARIO_KINDS:
            raise ValueError(f"{scenario.id}: unknown kind {scenario.kind!r}")
        if scenario.repo not in repos:
            raise ValueError(f"{scenario.id}: unknown repository {scenario.repo!r}")
        if scenario.id in seen:
            raise ValueError(f"duplicate scenario id {scenario.id!r}")
        if scenario.kind == "seeded" and not scenario.patch:
            raise ValueError(f"{scenario.id}: a seeded scenario needs a patch")
        seen.add(scenario.id)
        scenarios.append(scenario)
    return Plan(
        budget=float(data["budget"]),
        max_cost_per_run=float(data["max_cost_per_run"]),
        extra_spent=float(data.get("extra_spent", 0.0)),
        setup={name: repo.get("setup", {}) for name, repo in repos.items()},
        scenarios=tuple(scenarios),
    )


def run_cost(saved: Mapping[str, Any]) -> float:
    """Cost of one saved run in USD; 0 when no report or no price."""
    report = saved.get("report") or {}
    return float((report.get("usage") or {}).get("cost_usd") or 0.0)


def can_afford(spent: float, max_cost_per_run: float, budget: float) -> bool:
    """Whether one more run, at its worst-case cost, stays within the budget."""
    return spent + max_cost_per_run <= budget + 1e-9


def _git(repo: Path, *arguments: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)}: {result.stderr.strip()}")
    return result.stdout


def _prepare(
    clone: Path,
    tree: Path,
    scenario: Scenario,
    plan_dir: Path,
    setup: Mapping[str, str],
) -> None:
    base = scenario.commit + ("^" if scenario.kind == "forward" else "")
    _git(clone, "worktree", "add", "--detach", str(tree), base)
    if setup:
        for relative, content in setup.items():
            (tree / relative).parent.mkdir(parents=True, exist_ok=True)
            (tree / relative).write_text(content)
        _git(tree, "add", "--force", *setup)
        _git(tree, *GIT_IDENTITY, "commit", "--quiet", "-m", "evaluation setup")
    if scenario.kind == "seeded":
        assert scenario.patch is not None
        _git(tree, "apply", str((plan_dir / scenario.patch).resolve()))
        return
    diff = _git(clone, "diff", "--binary", f"{scenario.commit}^", scenario.commit)
    reverse = ["--reverse"] if scenario.kind == "replay" else []
    _git(tree, "apply", *reverse, "-", stdin=diff)


def check_command(
    scenario: Scenario, python: Path, output_dir: Path, max_cost: float
) -> list[str]:
    """The ``didibreak check`` command line for one scenario."""
    return [
        "didibreak",
        "check",
        "--format",
        "json",
        "--intent",
        scenario.intent,
        "--max-cost",
        str(max_cost),
        "--python",
        str(python),
        "--output-dir",
        str(output_dir),
    ]


def run_scenario(
    scenario: Scenario, plan: Plan, plan_dir: Path, repos: Path, python: Path
) -> dict[str, Any]:
    """Prepare the tree, run the check and return what is saved for it."""
    clone = repos / scenario.repo
    temporary = Path(tempfile.mkdtemp(prefix="didibreak-eval-"))
    tree = temporary / scenario.id
    try:
        _prepare(clone, tree, scenario, plan_dir, plan.setup[scenario.repo])
        command = check_command(
            scenario, python, temporary / "out", plan.max_cost_per_run
        )
        executable = Path(sys.executable).with_name("didibreak")
        started = time.monotonic()
        result = subprocess.run(
            [str(executable), *command[1:]],
            cwd=tree,
            capture_output=True,
            text=True,
            check=False,
        )
        seconds = round(time.monotonic() - started, 1)
        report = json.loads(result.stdout) if result.stdout.strip() else None
        shown = [*command[:-2], "--output-dir", "<temporary>"]
        shown[shown.index("--python") + 1] = "<python>"
        return {
            "scenario": scenario.__dict__,
            "base_sha": _git(tree, "rev-parse", "HEAD").strip(),
            "command": shown,
            "exit_code": result.returncode,
            "seconds": seconds,
            "stderr": result.stderr.replace(str(temporary), "<temporary>"),
            "report": report,
        }
    finally:
        subprocess.run(
            ["git", "-C", str(clone), "worktree", "remove", "--force", str(tree)],
            capture_output=True,
            check=False,
        )
        shutil.rmtree(temporary, ignore_errors=True)


def run(plan_path: Path, repos: Path, python: Path) -> int:
    """Run every scenario without a saved report, within the budget."""
    plan = load_plan(plan_path)
    reports = plan_path.parent / "reports"
    reports.mkdir(exist_ok=True)
    for scenario in plan.scenarios:
        destination = reports / f"{scenario.id}.json"
        if destination.exists():
            continue
        spent = plan.extra_spent + sum(
            run_cost(json.loads(p.read_text())) for p in reports.glob("*.json")
        )
        if not can_afford(spent, plan.max_cost_per_run, plan.budget):
            print(f"budget: ${spent:.4f} spent; stopping before {scenario.id}")
            return 1
        saved = run_scenario(scenario, plan, plan_path.parent, repos, python)
        destination.write_text(json.dumps(saved, indent=2) + "\n")
        print(
            f"{scenario.id}: exit {saved['exit_code']}, {saved['seconds']} s, "
            f"${run_cost(saved):.4f}"
        )
    return 0


def skip_category(reason: str) -> str:
    """Group a skip reason: drop names and versions after the first colon."""
    category = reason.removesuffix(" (base version)")
    return category.split(":", 1)[0].strip()


def precision(real: int, labelled: int) -> float | None:
    """Share of labelled unexpected findings that are real; None if none."""
    return real / labelled if labelled else None


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


@dataclass
class _Totals:
    scenarios: int = 0
    checked: int = 0
    skipped: int = 0
    cost: float = 0.0
    labels: Counter[str] | None = None
    real: int = 0
    unexpected: int = 0

    def add(
        self, report: Mapping[str, Any], cost: float, real: int, unexpected: int
    ) -> None:
        self.scenarios += 1
        self.checked += report["summary"]["functions_checked"]
        self.skipped += len(report["summary"]["skipped"])
        self.cost += cost
        self.labels = (self.labels or Counter()) + Counter(
            finding["label"] for finding in report["findings"]
        )
        self.real += real
        self.unexpected += unexpected

    def row(self, name: str) -> str:
        labels = self.labels or Counter()
        counts = " / ".join(
            str(labels[label])
            for label in ("unexpected", "unclear", "expected", "new_function")
        )
        return (
            f"| {name} | {self.scenarios} | {self.checked} | {self.skipped} | "
            f"{counts} | {self.real} / {self.unexpected} | "
            f"{_percent(precision(self.real, self.unexpected))} | "
            f"${self.cost:.4f} |"
        )


def summarize(plan_path: Path) -> str:
    """Markdown tables of the saved reports and hand labels."""
    plan = load_plan(plan_path)
    labels_path = plan_path.parent / "labels.json"
    labels = json.loads(labels_path.read_text()) if labels_path.exists() else {}
    per_repo: dict[str, _Totals] = {}
    overall = _Totals()
    skips: Counter[str] = Counter()
    unlabelled: list[str] = []
    for scenario in plan.scenarios:
        path = plan_path.parent / "reports" / f"{scenario.id}.json"
        if not path.exists():
            continue
        saved = json.loads(path.read_text())
        report = saved["report"]
        if report is None:
            continue
        real = unexpected = 0
        for finding in report["findings"]:
            if finding["label"] != "unexpected":
                continue
            key = f"{scenario.id}/{finding['id']}"
            if key not in labels:
                unlabelled.append(key)
                continue
            unexpected += 1
            real += bool(labels[key]["real"])
        skips.update(
            skip_category(item["reason"]) for item in report["summary"]["skipped"]
        )
        for totals in (per_repo.setdefault(scenario.repo, _Totals()), overall):
            totals.add(report, run_cost(saved), real, unexpected)
    header = (
        "| Repository | Runs | Checked | Skipped | Unexpected / unclear / "
        "expected / new_function | Real / labelled unexpected | Precision "
        "| Cost |\n| --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    rows = [totals.row(name) for name, totals in per_repo.items()]
    lines = [
        header,
        *rows,
        overall.row("**All**"),
        "",
        "| Skip reason | Count |",
        "| --- | --- |",
    ]
    lines += [f"| {reason} | {count} |" for reason, count in skips.most_common()]
    if unlabelled:
        lines += ["", "Unlabelled unexpected findings: " + ", ".join(unlabelled)]
    return "\n".join(lines)


def copy_seconds(repositories: Iterable[Path]) -> list[tuple[str, int, float]]:
    """Time didibreak's working-tree copy for each repository.

    Returns:
        Repository name, number of files copied and seconds, per repository.
    """
    from didibreak.gitdiff import visible_files, working_tree_copy

    timings = []
    for repository in repositories:
        started = time.monotonic()
        with working_tree_copy(repository):
            seconds = time.monotonic() - started
        timings.append((repository.name, len(visible_files(repository)), seconds))
    return timings


def main(arguments: Sequence[str]) -> int:
    """Command-line entry point; see the module docstring."""
    if len(arguments) == 4 and arguments[0] == "run":
        return run(Path(arguments[1]), Path(arguments[2]), Path(arguments[3]))
    if len(arguments) == 2 and arguments[0] == "summarize":
        print(summarize(Path(arguments[1])))
        return 0
    if len(arguments) >= 2 and arguments[0] == "copy-time":
        for name, files, seconds in copy_seconds(Path(a) for a in arguments[1:]):
            print(f"| {name} | {files} | {seconds:.2f} s |")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
