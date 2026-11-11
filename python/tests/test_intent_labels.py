"""Labelling findings against the intent, with fake LLM replies."""

from typing import Any

import pytest

from didibreak.cases import load_template
from didibreak.compare import Finding
from didibreak.config import Config
from didibreak.harness import Case, Outcome
from didibreak.intent import (
    LABEL_PROMPT_FILE,
    LABELS_SCHEMA,
    MAX_LABELLED_FINDINGS,
    NO_INTENT_REASON,
    NOT_LABELLED_REASON,
    TOO_MANY_REASON,
    apply_labels,
    build_label_messages,
    mark_unclear,
    to_label,
)
from didibreak.llm.common import schema_errors
from didibreak.llm_session import LLMSession
from didibreak.pipeline import TOKEN_LIMIT_REASON, Budget

PHONE = "app/utils/phone.py::normalize_phone"


def finding(
    identifier: str, label: str = "unclear", before: str | None = "'a'"
) -> Finding:
    old = None if before is None else Outcome("return", "builtins.str", before)
    new = Outcome("return", "builtins.str", "'b'")
    return Finding(
        identifier, PHONE, Case((f"'{identifier}'",)), old, new, "high", label
    )


def reply(*labels: tuple[str, str]) -> dict[str, Any]:
    return {
        "labels": [
            {"finding_id": i, "label": label, "reason": f"because {i}"}
            for i, label in labels
        ]
    }


@pytest.mark.parametrize("label", ["expected", "unexpected", "unclear"])
def test_each_label_is_applied_with_its_reason(label: str) -> None:
    (labelled,) = apply_labels([finding("f1")], reply(("f1", label)))

    assert (labelled.label, labelled.reason) == (label, "because f1")


def test_labels_never_remove_findings_and_keep_order() -> None:
    findings = [finding("f1"), finding("f2"), finding("f3")]

    labelled = apply_labels(findings, reply(("f3", "expected"), ("zz", "unexpected")))

    assert [f.id for f in labelled] == ["f1", "f2", "f3"]
    assert [f.label for f in labelled] == ["unclear", "unclear", "expected"]
    assert labelled[0].reason == NOT_LABELLED_REASON


@pytest.mark.parametrize(
    "data",
    [
        {"labels": [{"finding_id": "f1", "label": "fine", "reason": "r"}]},
        {"labels": [{"finding_id": 1, "label": "expected", "reason": "r"}]},
        {"labels": ["f1"]},
        {"labels": []},
        {},
    ],
)
def test_malformed_labels_leave_the_finding_unclear(data: dict[str, Any]) -> None:
    (labelled,) = apply_labels([finding("f1")], data)

    assert (labelled.label, labelled.reason) == ("unclear", NOT_LABELLED_REASON)


def test_first_label_for_an_id_wins() -> None:
    data = reply(("f1", "expected"), ("f1", "unexpected"))

    (labelled,) = apply_labels([finding("f1")], data)

    assert labelled.label == "expected"


def test_new_function_findings_keep_their_label_and_are_not_sent() -> None:
    new = finding("n1", label="new_function", before=None)
    findings = [new, finding("f1")]

    labelled = apply_labels(findings, reply(("n1", "expected"), ("f1", "unexpected")))

    assert labelled[0] == new
    assert to_label(findings) == [findings[1]]


def test_findings_beyond_the_maximum_stay_unclear() -> None:
    findings = [finding(f"f{n}") for n in range(MAX_LABELLED_FINDINGS + 2)]
    data = reply(*((f.id, "expected") for f in findings))

    labelled = apply_labels(findings, data)

    assert len(to_label(findings)) == MAX_LABELLED_FINDINGS
    assert labelled[-1].label == "unclear"
    assert labelled[-1].reason == TOO_MANY_REASON
    assert labelled[0].label == "expected"


def test_without_intent_all_findings_are_unclear() -> None:
    new = finding("n1", label="new_function", before=None)

    labelled = mark_unclear([finding("f1", "expected"), new], NO_INTENT_REASON)

    assert (labelled[0].label, labelled[0].reason) == ("unclear", NO_INTENT_REASON)
    assert labelled[1] == new


def test_prompt_lists_every_finding_with_both_outcomes() -> None:
    template = load_template(LABEL_PROMPT_FILE)

    system, user = build_label_messages(
        "Stated by the user: add international phone numbers",
        [finding("c2b1f5a53a6d")],
        template,
    )

    assert template.version == 1
    assert 'use "unclear"' in system.content
    assert "Stated by the user: add international phone numbers" in user.content
    assert (
        "- finding_id c2b1f5a53a6d: normalize_phone('c2b1f5a53a6d') in "
        f"{PHONE} -> old: 'a'; new: 'b'" in user.content
    )


def test_label_schema_is_strict_and_accepts_a_valid_reply() -> None:
    assert schema_errors(reply(("f1", "expected")), LABELS_SCHEMA) == []
    assert schema_errors(reply(("f1", "maybe")), LABELS_SCHEMA)


def test_labelling_over_the_token_limit_sends_nothing_and_says_why() -> None:
    def no_client(config: Config, environment: object) -> object:
        raise AssertionError("no request may be sent")

    config = Config(no_cache=True, provider="openai")
    session = LLMSession.open(config, {"OPENAI_API_KEY": "sk-fake"}, no_client)
    session.budget = Budget(None, None, config.cases, max_tokens=1)

    (labelled,) = session.label([finding("f1")], "the intent", NO_INTENT_REASON)

    assert labelled.label == "unclear"
    assert labelled.reason == f"intent labelling failed: {TOKEN_LIMIT_REASON}"
