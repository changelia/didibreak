# didibreak — instructions for AI coding agents

This file is read by Claude Code at the start of every session. The full rules live in Notion
and override anything you would otherwise assume.

## Source of truth: Notion
Before any task, read these pages with the Notion MCP tools:
- Project hub: https://app.notion.com/p/40dcab7562dc81d68626c682ebd03b1b
- Working Rules & Decision Log (read first, every session): https://app.notion.com/p/40dcab7562dc81738ca9e9b0281a1de9
- Spec: https://app.notion.com/p/40dcab7562dc8138b846e3b266196911
- Architecture: https://app.notion.com/p/40dcab7562dc8111bf37cff60eb3ffec
- Detailed Design: https://app.notion.com/p/40dcab7562dc817da672eb24ad12d4a7
- Competitor Research: https://app.notion.com/p/40dcab7562dc81c09d71f8d05ba8be2c
- Tasks database: https://app.notion.com/p/06a070dfa71e4b67902c4d227482ab66
If the Notion tools are not available, stop and tell the owner. Do not work from memory of the spec.

## Non-negotiable rules (summary — Notion has the full list)
1. Never invent. If something is missing or ambiguous, stop and ask the owner, and record the
   question under "Open questions" on the Working Rules page.
2. One task at a time, only the task the owner named: read task → propose plan → wait for approval
   → implement on a feature branch → run checks → report → update Notion.
3. Feature branch per task (task-NN-short-name). Small commits: one logical change each,
   about 200 changed lines max (excluding lock files), tests in the same commit, every commit
   passes all checks. Semantic commit messages: type(scope): subject — types feat, fix, refactor,
   test, docs, ci, build, chore, perf; scopes python, spec, docs, ci; imperative, max 72 chars;
   footer "Refs: task NN". See "Commit rules" in Notion.
   Never push to main, merge, tag, bump versions or publish without explicit owner approval.
4. Every code change: tests added; in python/ run uv run pytest, uv run ruff check .,
   uv run ruff format --check ., uv run mypy src (strict mode is configured in
   python/pyproject.toml via [tool.mypy] strict = true, added in task 03).
   Report exact commands and real output.
5. No new dependencies without owner approval. Runtime dependency: httpx only.
6. Product invariants: no server, no database, users bring their own API key, the tool never edits
   user code, LLM output is never executed as code.
7. Honest reporting: separate verified results from assumptions; never claim a check ran if it did not.
8. All code, comments, docs, commits, PRs and Notion task content in English.
9. A Notion task stays "Planned" until implemented and verified; fill "Completion evidence"
   (branch, commit SHAs, commands, results, limitations) before setting "Completed".

## Repository layout
Monorepo: python/ (PyPI package), spec/ (shared contract), docs/ (user docs), js/ (later).
Details: Architecture page in Notion.
