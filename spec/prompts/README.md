# Prompt templates

Versioned LLM prompt templates shared by all didibreak packages. Each template
starts with a version header (`prompt_version: 1`).

- Case generation and refinement: written in task 14.
- Intent labelling: written in task 17.

This folder is the only place to edit prompts. The Python package copies it to
`python/src/didibreak/prompts/` at build time (see `python/scripts/sync_prompts.py`);
never edit that copy. This README is not copied.
