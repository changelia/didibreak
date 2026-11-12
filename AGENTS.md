# didibreak — instructions for AI coding agents

These rules apply to any AI agent (Claude Code, Codex, Cursor, ...) working
on this repository, and to the people who run them. They are a summary of
[CONTRIBUTING.md](CONTRIBUTING.md); when in doubt, CONTRIBUTING.md wins.

## Read first

- [CONTRIBUTING.md](CONTRIBUTING.md): setup, checks, repository layout, how to
  add a comparison rule or a provider, commit and pull request rules.
- [docs/](docs/): what didibreak does for users. `docs/how-it-works.md`,
  `docs/safety.md` and `docs/limitations.md` explain the design limits.
- `spec/`: the shared contract (JSON report schema, prompt templates).

## Product rules (never break these)

1. No server and no database: didibreak runs on the user's machine.
2. Users bring their own API key; keys never reach logs, reports, the cache
   or error messages.
3. didibreak never edits the user's code; it writes only to its output
   folder (`.didibreak/`).
4. LLM output is data, never code: arguments must pass `ast.literal_eval`.
5. `httpx` is the only runtime dependency. Do not add another one; dev-only
   tools must be pinned and explained in the pull request.

## Every change

- Add tests for the change (the positive case, a negative case, a
  regression). No real LLM calls in tests: use mocked transports.
- Run from `python/` and make all four pass:

  ```bash
  uv run pytest
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src
  ```

- Never pipe a check through a command that hides its exit code, such as
  `uv run pytest | tail`: the pipeline then succeeds even when tests fail.
  Run the check on its own, or use `set -o pipefail`, or check the exit
  status explicitly (`uv run pytest; echo "exit $?"`) before committing.
- Update the docs and `CHANGELOG.md` (Unreleased) when behavior, a flag, a
  config key or the output changes. Examples in the docs are real output.
- Report honestly: say which checks you ran and their real output; never
  claim a check passed if it did not run.
- Write code, comments, docs and commit messages in English.

## Commits and pull requests

- Work on a branch, never on `main`.
- One logical change per commit, about 200 changed lines at most (lock files
  excluded), tests in the same commit, every commit passes all checks.
- Conventional Commits: `type(scope): subject`, imperative, lowercase, at
  most 72 characters. Types: `feat`, `fix`, `refactor`, `test`, `docs`, `ci`,
  `build`, `chore`, `perf`. Scopes: `python`, `spec`, `docs`, `ci`.
- Footer `Refs: #<issue>` when the change belongs to an issue.
- No AI co-author trailers and no AI attribution lines in commits or pull
  requests.
- Do not push to `main`, merge, tag, bump versions or publish; the
  maintainer does that.

## Code style

- Small functions with one job and descriptive names; full type hints
  (`mypy --strict`); Google-style docstrings on public functions.
- Pure logic over data (frozen dataclasses); git, subprocesses, files and
  network stay at the edges.
- User-facing errors say what happened, why, and how to fix it.
