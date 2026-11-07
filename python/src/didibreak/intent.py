"""Intent labelling: what the change was meant to do, and labels for findings.

Pure functions over data; the LLM call is made by the session. The intent is
the ``--intent`` text and the messages of the commits since the base (the
commits in base..HEAD are part of the change). Labels never remove a
finding; without an intent every finding is ``unclear`` (Spec).
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from string import Template
from typing import Any

from didibreak.cases import PromptTemplate, describe_call, describe_outcome
from didibreak.compare import Finding
from didibreak.llm.common import Message

# Owner decision 2026-11-07 (task 17 review): all commit messages in
# base..HEAD, newest first, up to about this many characters in total.
COMMIT_MESSAGES_LIMIT = 4000
COMMIT_MESSAGES_HEADER = "Commit messages since the base (newest first):"


def _commit_messages_text(messages: Sequence[str]) -> str:
    kept: list[str] = []
    used = 0
    for message in (m.strip() for m in messages):
        if not message:
            continue
        room = COMMIT_MESSAGES_LIMIT - used
        if room <= 0:
            break
        # Whole messages are kept while they fit; only the first may be cut.
        if len(message) > room and kept:
            break
        kept.append(message[:room])
        used += len(kept[-1])
    return "\n\n".join(f"- {message}" for message in kept)


def intent_text(intent: str | None, commit_messages: Sequence[str]) -> str | None:
    """The intent shown to the LLM, or None when there is none.

    Args:
        intent: The ``--intent`` text.
        commit_messages: Messages of the commits in base..HEAD, newest first.

    Returns:
        Both parts, labelled, or None when both are empty.
    """
    parts = []
    if intent and intent.strip():
        parts.append(f"Stated by the user: {intent.strip()}")
    messages = _commit_messages_text(commit_messages)
    if messages:
        parts.append(f"{COMMIT_MESSAGES_HEADER}\n{messages}")
    return "\n\n".join(parts) or None


LABELS = ("expected", "unexpected", "unclear")
UNCLEAR = "unclear"
NEW_FUNCTION = "new_function"
LABEL_PROMPT_FILE = "intent_labelling.md"
LABELS_SCHEMA_NAME = "didibreak_labels"
# One request labels at most this many findings; the rest stay unclear.
MAX_LABELLED_FINDINGS = 50
NO_INTENT_REASON = "no intent was given (--intent or a commit message)"
NOT_LABELLED_REASON = "the LLM gave no usable label for this finding"
TOO_MANY_REASON = "too many findings to label in one request"
LABELS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "label": {"type": "string", "enum": list(LABELS)},
                    "reason": {"type": "string"},
                },
                "required": ["finding_id", "label", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def to_label(findings: Sequence[Finding]) -> list[Finding]:
    """Findings sent for labelling: not new_function, at most the maximum."""
    eligible = [f for f in findings if f.label != NEW_FUNCTION]
    return eligible[:MAX_LABELLED_FINDINGS]


def _finding_line(finding: Finding) -> str:
    qualname = finding.function.rpartition("::")[2]
    call = describe_call(qualname, finding.case)
    old = "none" if finding.before is None else describe_outcome(finding.before)
    new = describe_outcome(finding.after)
    return (
        f"- finding_id {finding.id}: {call} in {finding.function} -> "
        f"old: {old}; new: {new}"
    )


def build_label_messages(
    intent: str, findings: Sequence[Finding], template: PromptTemplate
) -> list[Message]:
    """The labelling conversation for the findings of one run."""
    user = Template(template.user).substitute(
        intent=intent,
        findings="\n".join(_finding_line(finding) for finding in findings),
    )
    return [Message("system", template.system), Message("user", user)]


def mark_unclear(findings: Sequence[Finding], reason: str) -> tuple[Finding, ...]:
    """Every finding except new_function ones becomes unclear with a reason."""
    return tuple(
        f if f.label == NEW_FUNCTION else replace(f, label=UNCLEAR, reason=reason)
        for f in findings
    )


def apply_labels(
    findings: Sequence[Finding], data: Mapping[str, Any]
) -> tuple[Finding, ...]:
    """Put the LLM's labels on the findings; nothing is ever removed.

    Args:
        findings: All findings of the run, in report order.
        data: The schema-valid reply (``{"labels": [...]}``).

    Returns:
        The same findings: labelled when the reply has a valid label for the
        id, ``unclear`` otherwise; new_function findings keep their label.
    """
    labels: dict[str, tuple[str, str]] = {}
    for item in data.get("labels", []):
        if not isinstance(item, dict):
            continue
        key, label, reason = (
            item.get("finding_id"),
            item.get("label"),
            item.get("reason"),
        )
        if isinstance(key, str) and label in LABELS and key not in labels:
            labels[key] = (str(label), reason if isinstance(reason, str) else "")
    sent = {f.id for f in to_label(findings)}
    labelled = []
    for finding in findings:
        if finding.label == NEW_FUNCTION:
            labelled.append(finding)
        elif finding.id in labels and finding.id in sent:
            label, reason = labels[finding.id]
            labelled.append(replace(finding, label=label, reason=reason))
        else:
            reason = NOT_LABELLED_REASON if finding.id in sent else TOO_MANY_REASON
            labelled.append(replace(finding, label=UNCLEAR, reason=reason))
    return tuple(labelled)
