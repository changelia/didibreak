"""Case generation: the prompt for one function and the checks on the LLM's cases.

Pure functions over data; the LLM call itself is made by the pipeline. The
prompt template is a versioned file (spec/prompts/case_generation.md, copied
into the package at build time). Every proposed argument must pass
``ast.literal_eval``: the LLM supplies data, never code (Spec, Safety).
"""

import ast
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from string import Template
from typing import Any

from didibreak.arguments import case_problem, format_call
from didibreak.compare import finding_id
from didibreak.functions import ChangedFunction
from didibreak.harness import Case, Outcome
from didibreak.llm.common import Message

PROMPT_FILE = "case_generation.md"
REFINEMENT_PROMPT_FILE = "case_refinement.md"
# Previous results in a refinement prompt: keep it short and bounded.
OUTCOME_TEXT_LIMIT = 120
MAX_PREVIOUS_CASES = 50
_SYSTEM_MARKER = "=== system ==="
_USER_MARKER = "=== user ==="

CHANGED_TASK = (
    "Find inputs on which the old and the new version behave differently: a "
    "different return value, a different exception type, or one raising while "
    "the other returns."
)
NEW_TASK = (
    "This function is new; there is no old version. Find reasonable inputs on "
    "which it raises an unexpected exception or does not finish."
)
NO_OLD_SOURCE = "(none: new function)"

CASES_SCHEMA_NAME = "didibreak_cases"
# Strict structured output needs additionalProperties false on every object,
# so keyword arguments are name/value pairs (task 12, accepted by the owner).
CASES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "args": {"type": "array", "items": {"type": "string"}},
                    "kwargs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["args", "kwargs", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cases"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class PromptTemplate:
    """A parsed prompt file: version and the two message templates."""

    version: int
    system: str
    user: str


def parse_template(text: str) -> PromptTemplate:
    """Parse a prompt file (format described in spec/prompts/README.md).

    Args:
        text: File content.

    Returns:
        The template.

    Raises:
        ValueError: The version header or a section marker is missing.
    """
    header, _, rest = text.partition("\n")
    name, _, value = header.partition(":")
    if name.strip() != "prompt_version" or not value.strip().isdigit():
        raise ValueError("prompt file must start with 'prompt_version: N'")
    before, found_system, after_system = rest.partition(_SYSTEM_MARKER)
    system, found_user, user = after_system.partition(_USER_MARKER)
    if not (found_system and found_user) or before.strip():
        raise ValueError(f"prompt file needs '{_SYSTEM_MARKER}' then '{_USER_MARKER}'")
    return PromptTemplate(int(value), system.strip(), user.strip())


def load_template(name: str = PROMPT_FILE) -> PromptTemplate:
    """Read a prompt template shipped in the package (didibreak/prompts/)."""
    text = resources.files("didibreak").joinpath("prompts", name).read_text("utf-8")
    return parse_template(text)


def _function_node(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(textwrap.dedent(source))
    node = tree.body[0]
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        raise ValueError("source does not start with a function definition")
    return node


def signature(source: str) -> str:
    """``def name(arguments) -> annotation`` of a function's source."""
    node = _function_node(source)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"def {node.name}({ast.unparse(node.args)}){returns}"


def docstring(source: str) -> str:
    """The function's docstring, or ``(none)``."""
    return ast.get_docstring(_function_node(source)) or "(none)"


def build_messages(
    function: ChangedFunction, count: int, template: PromptTemplate
) -> list[Message]:
    """The case-generation conversation for one function.

    Args:
        function: A testable changed or new function.
        count: Number of cases to request.
        template: The parsed prompt template.

    Returns:
        System and user messages.

    Raises:
        KeyError: The template uses a placeholder this function does not fill.
    """
    is_new = function.old_source is None
    user = Template(template.user).substitute(
        function=function.report_name,
        signature=signature(function.new_source),
        docstring=docstring(function.new_source),
        task=NEW_TASK if is_new else CHANGED_TASK,
        old_source=(function.old_source or NO_OLD_SOURCE).rstrip(),
        new_source=function.new_source.rstrip(),
        count=count,
    )
    return [Message("system", template.system), Message("user", user)]


@dataclass(frozen=True)
class CaseRun:
    """A case and what both versions did with it (base None for new functions)."""

    case: Case
    before: Outcome | None
    after: Outcome


def describe_call(qualname: str, case: Case) -> str:
    """``name(arg, key=value)`` as written in the case."""
    return format_call(qualname.rsplit(".", 1)[-1], case.args, case.kwargs)


def describe_outcome(outcome: Outcome) -> str:
    """Short text of one outcome for a refinement prompt."""
    if outcome.kind == "exception":
        text = f"raises {outcome.type_name}"
    elif outcome.kind == "timeout":
        text = "timed out"
    else:
        text = outcome.repr[:OUTCOME_TEXT_LIMIT]
    return text if outcome.stable else f"{text} (not repeatable)"


def _previous_lines(qualname: str, previous: Sequence[CaseRun]) -> str:
    lines = []
    for run in previous[-MAX_PREVIOUS_CASES:]:
        call = describe_call(qualname, run.case)
        if run.before is None:
            lines.append(f"- {call} -> {describe_outcome(run.after)}")
        else:
            lines.append(
                f"- {call} -> old: {describe_outcome(run.before)}; "
                f"new: {describe_outcome(run.after)}"
            )
    return "\n".join(lines) or "(none)"


def build_refinement_messages(
    function: ChangedFunction,
    count: int,
    template: PromptTemplate,
    previous: Sequence[CaseRun],
) -> list[Message]:
    """The refinement conversation: the generation inputs plus the cases tried.

    Args:
        function: A function whose cases showed no difference.
        count: Number of new cases to request.
        template: The parsed refinement template.
        previous: Cases already tried with both outcomes, oldest first; at
            most MAX_PREVIOUS_CASES (the latest) are listed.

    Returns:
        System and user messages.
    """
    is_new = function.old_source is None
    user = Template(template.user).substitute(
        function=function.report_name,
        signature=signature(function.new_source),
        docstring=docstring(function.new_source),
        task=NEW_TASK if is_new else CHANGED_TASK,
        old_source=(function.old_source or NO_OLD_SOURCE).rstrip(),
        new_source=function.new_source.rstrip(),
        previous=_previous_lines(function.qualname, previous),
        count=count,
    )
    return [Message("system", template.system), Message("user", user)]


@dataclass(frozen=True)
class CaseBatch:
    """Cases accepted from one LLM reply.

    Attributes:
        cases: Valid, distinct cases in reply order, at most the number asked.
        invalid: Cases dropped because an argument is not a Python literal,
            too long, or a keyword name is unusable (summary
            ``invalid_cases_dropped``).
    """

    cases: tuple[Case, ...]
    invalid: int


def _keyword_arguments(pairs: object) -> dict[str, object] | None:
    # The schema sends keyword arguments as {name, value} pairs (task 12).
    if not isinstance(pairs, list):
        return None
    kwargs: dict[str, object] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            return None
        name, value = pair.get("name"), pair.get("value")
        if not isinstance(name, str) or name in kwargs:
            return None
        kwargs[name] = value
    return kwargs


def _case(item: object) -> Case | None:
    if not isinstance(item, dict):
        return None
    args = item.get("args")
    kwargs = _keyword_arguments(item.get("kwargs", []))
    if not isinstance(args, list) or kwargs is None:
        return None
    if case_problem(args, kwargs) is not None:
        return None
    rationale = item.get("rationale")
    return Case(
        tuple(str(a) for a in args),
        {name: str(value) for name, value in kwargs.items()},
        rationale if isinstance(rationale, str) else "",
    )


def accept_cases(data: Mapping[str, Any], count: int, function: str) -> CaseBatch:
    """Validate and deduplicate the cases of one LLM reply.

    Args:
        data: The schema-valid reply (``{"cases": [...]}``).
        count: Cases requested; later ones are ignored.
        function: Report name; duplicates are found with the finding id, so
            ``'a'`` and ``"a"`` are the same argument.

    Returns:
        The accepted cases and the number of invalid ones.
    """
    accepted: list[Case] = []
    seen: set[str] = set()
    invalid = 0
    for item in data.get("cases", []):
        if len(accepted) == count:
            break
        case = _case(item)
        if case is None:
            invalid += 1
            continue
        key = finding_id(function, case)
        if key not in seen:
            seen.add(key)
            accepted.append(case)
    return CaseBatch(tuple(accepted), invalid)
