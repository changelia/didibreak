"""Case generation: the prompt for one function and the checks on the LLM's cases.

Pure functions over data; the LLM call itself is made by the pipeline. The
prompt template is a versioned file (spec/prompts/case_generation.md, copied
into the package at build time). Every proposed argument must pass
``ast.literal_eval``: the LLM supplies data, never code (Spec, Safety).
"""

import ast
import textwrap
from dataclasses import dataclass
from importlib import resources
from string import Template

from didibreak.functions import ChangedFunction
from didibreak.llm.common import Message

PROMPT_FILE = "case_generation.md"
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
