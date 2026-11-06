# Prompt templates

Versioned LLM prompt templates shared by all didibreak packages. Each template
starts with a version header (`prompt_version: 1`).

- `case_generation.md` (task 14): asks for input cases for one changed or
  new function. Refinement follows in task 16.
- Intent labelling: written in task 17.

Format: the first line is `prompt_version: N`; `=== system ===` and
`=== user ===` start the two messages. Placeholders use Python
`string.Template` syntax (`$name`); write `$$` for a literal dollar sign.
Change `prompt_version` whenever the wording changes, because cached cases
are keyed by it.

This folder is the only place to edit prompts. The Python package copies it to
`python/src/didibreak/prompts/` at build time (see `python/scripts/sync_prompts.py`);
never edit that copy. This README is not copied.
