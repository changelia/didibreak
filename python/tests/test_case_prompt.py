import pytest

from didibreak.cases import (
    CHANGED_TASK,
    MAX_PREVIOUS_CASES,
    NEW_TASK,
    NO_OLD_SOURCE,
    OUTCOME_TEXT_LIMIT,
    REFINEMENT_PROMPT_FILE,
    CaseRun,
    PromptTemplate,
    build_messages,
    build_refinement_messages,
    docstring,
    load_template,
    parse_template,
    signature,
)
from didibreak.functions import ChangedFunction
from didibreak.harness import Case, Outcome

OLD = "def normalize_phone(raw):\n    return '+995' + raw\n"
NEW = (
    "def normalize_phone(raw: str, *, strict: bool = False) -> str:\n"
    '    """Return a phone number in +995 format."""\n'
    "    return '$' + raw\n"
)


def function(old: str | None = OLD, new: str = NEW) -> ChangedFunction:
    return ChangedFunction(
        file="app/utils/phone.py",
        module="app.utils.phone",
        qualname="normalize_phone",
        kind="changed" if old else "new",
        function_type="function",
        is_async=False,
        line=1,
        old_source=old,
        new_source=new,
    )


def test_packaged_template_has_a_version_and_both_messages() -> None:
    template = load_template()

    assert template.version == 1
    assert "Python literal" in template.system
    assert "$new_source" in template.user


def test_messages_contain_both_versions_signature_and_count() -> None:
    system, user = build_messages(function(), 12, load_template())

    assert system.role == "system"
    assert user.role == "user"
    assert "Function: app/utils/phone.py::normalize_phone" in user.content
    assert (
        "Signature: def normalize_phone(raw: str, *, strict: bool=False) -> str"
        in user.content
    )
    assert "Docstring: Return a phone number in +995 format." in user.content
    assert CHANGED_TASK in user.content
    assert "return '+995' + raw" in user.content
    assert "return '$' + raw" in user.content  # a $ in the source is kept
    assert "Propose 12 cases." in user.content


def test_new_functions_say_there_is_no_old_version() -> None:
    _, user = build_messages(function(old=None), 3, load_template())

    assert NEW_TASK in user.content
    assert NO_OLD_SOURCE in user.content


def test_methods_and_missing_docstrings() -> None:
    method = "@staticmethod\ndef parse(text, *args, **kwargs):\n    return text\n"

    assert signature(method) == "def parse(text, *args, **kwargs)"
    assert docstring(method) == "(none)"


def test_template_parsing() -> None:
    text = "prompt_version: 3\n=== system ===\nS\n=== user ===\nU $x\n"

    assert parse_template(text) == PromptTemplate(3, "S", "U $x")


@pytest.mark.parametrize(
    "text",
    [
        "=== system ===\nS\n=== user ===\nU",
        "prompt_version: x\n=== system ===\nS\n=== user ===\nU",
        "prompt_version: 1\n=== user ===\nU",
        "prompt_version: 1\nstray\n=== system ===\nS\n=== user ===\nU",
    ],
)
def test_malformed_templates_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_template(text)


def test_unknown_placeholder_is_an_error() -> None:
    template = PromptTemplate(1, "S", "$unknown")

    with pytest.raises(KeyError):
        build_messages(function(), 1, template)


def outcome(repr_text: str, kind: str = "return", stable: bool = True) -> Outcome:
    type_name = "builtins.ValueError" if kind == "exception" else "builtins.str"
    return Outcome(kind, type_name, repr_text, stable=stable)


def test_refinement_template_is_packaged() -> None:
    template = load_template(REFINEMENT_PROMPT_FILE)

    assert template.version == 1
    assert "$previous" in template.user
    assert "differ from all cases already tried" in template.system


def test_refinement_lists_previous_cases_with_both_outcomes() -> None:
    previous = [
        CaseRun(
            Case(("'555 12 34 56'",)),
            outcome("'+995555123456'"),
            outcome("'+995555123456'"),
        ),
        CaseRun(
            Case(("''",), {"strict": "True"}),
            outcome("E()", "exception"),
            outcome("E()", "exception"),
        ),
        CaseRun(Case(("'x'",)), outcome("'a'", stable=False), outcome("'b'")),
    ]

    _, user = build_refinement_messages(
        function(), 4, load_template(REFINEMENT_PROMPT_FILE), previous
    )

    assert (
        "- normalize_phone('555 12 34 56') -> old: '+995555123456'; "
        "new: '+995555123456'" in user.content
    )
    assert (
        "- normalize_phone('', strict=True) -> old: raises builtins.ValueError; "
        "new: raises builtins.ValueError" in user.content
    )
    assert "old: 'a' (not repeatable)" in user.content
    assert "Propose 4 new cases" in user.content
    assert "return '$' + raw" in user.content


def test_refinement_for_a_new_function_shows_one_outcome() -> None:
    previous = [CaseRun(Case(("1",)), None, Outcome("timeout", "", "<t>"))]

    _, user = build_refinement_messages(
        function(old=None), 2, load_template(REFINEMENT_PROMPT_FILE), previous
    )

    assert "- normalize_phone(1) -> timed out" in user.content
    assert NEW_TASK in user.content


def test_refinement_lists_at_most_the_latest_cases_and_cuts_long_values() -> None:
    previous = [
        CaseRun(Case((str(n),)), outcome("'" + "v" * 500 + "'"), outcome("'w'"))
        for n in range(MAX_PREVIOUS_CASES + 5)
    ]

    _, user = build_refinement_messages(
        function(), 2, load_template(REFINEMENT_PROMPT_FILE), previous
    )

    assert "normalize_phone(4) ->" not in user.content
    assert f"normalize_phone({MAX_PREVIOUS_CASES + 4}) ->" in user.content
    assert "v" * (OUTCOME_TEXT_LIMIT + 1) not in user.content
