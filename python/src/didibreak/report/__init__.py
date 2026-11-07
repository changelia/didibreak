"""Reports: the data of one check run, rendered as text or JSON (task 18).

``Report`` holds everything both formats show; report/text.py and
report/json.py only render it. Detailed Design sections 6 (JSON,
schema_version 1) and 7 (text) define the output.
"""

from dataclasses import dataclass

from didibreak.compare import Finding

LABEL_ORDER = ("unexpected", "unclear", "expected", "new_function")


@dataclass(frozen=True)
class SkippedItem:
    """A function (or file) that was not checked, and why."""

    function: str
    reason: str


@dataclass(frozen=True)
class ReportUsage:
    """LLM use of the run.

    Attributes:
        calls: Requests sent.
        input_tokens: Input tokens, cached ones included.
        output_tokens: Output tokens, reasoning tokens included.
        reasoning_tokens: Reasoning tokens inside output_tokens, if reported.
        cost_usd: US dollars; None when unknown.
        local: The model runs on this machine (cost 0).
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int | None = None
    cost_usd: float | None = 0.0
    local: bool = False


@dataclass(frozen=True)
class Report:
    """Everything a check run reports.

    Attributes:
        version: didibreak version.
        base_ref: ``--base`` as given.
        base_sha: Commit it resolved to.
        intent: Intent text used for labelling, or None.
        findings: Labelled findings in run order.
        functions_checked: Functions whose cases ran on both versions.
        cases_run: Cases run, refinement included.
        flaky_dropped: Cases dropped as flaky.
        invalid_cases_dropped: LLM cases that were not Python literals.
        skipped: Functions (and unreadable files) not checked, with reasons.
        removed: ``path::qualname`` of removed functions.
        usage: LLM use.
        refined: Functions that got refinement cases.
        refinement_cases: Cases run in refinement rounds.
        refinement_skipped: Checked functions whose refinement was skipped.
    """

    version: str
    base_ref: str
    base_sha: str
    intent: str | None
    findings: tuple[Finding, ...]
    functions_checked: int
    cases_run: int
    flaky_dropped: int
    invalid_cases_dropped: int
    skipped: tuple[SkippedItem, ...]
    removed: tuple[str, ...]
    usage: ReportUsage
    refined: int = 0
    refinement_cases: int = 0
    refinement_skipped: tuple[SkippedItem, ...] = ()

    def by_label(self) -> list[tuple[str, list[Finding]]]:
        """Findings grouped in report order: unexpected, unclear, expected, new."""
        return [
            (label, [f for f in self.findings if f.label == label])
            for label in LABEL_ORDER
        ]

    def counts(self) -> dict[str, int]:
        """Number of findings per label, every label present."""
        return {label: len(group) for label, group in self.by_label()}
