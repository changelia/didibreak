# Contributing

## Repository layout

One repository, one folder per package, a shared contract:

| Path | Contents |
| --- | --- |
| `python/` | PyPI package `didibreak` (uv + hatchling, `src/` layout). |
| `js/` | npm package, added after Python 0.1.0. |
| `spec/` | Shared contract: JSON report schema, prompt templates, shared test cases. |
| `docs/` | User documentation for all packages (plain Markdown). |

Each package builds only from its own folder. Files in `spec/` are the single
source; packages copy them at build time and never read across folders at
runtime.

## Python development setup

Requires [uv](https://docs.astral.sh/uv/) and `git`.

```bash
cd python
uv sync
```

`uv sync` installs the package in editable mode with the dev tools (pytest,
ruff, mypy) and copies `spec/prompts/` into `src/didibreak/prompts/`.

## Checks

Run from `python/`; every commit must pass all of them:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Ruff rules and mypy strict mode are configured in task 03.

## Prompt templates

Edit prompts only in `spec/prompts/`. After editing, refresh the package copy
and confirm it matches:

```bash
cd python
uv run python scripts/sync_prompts.py
uv run python scripts/sync_prompts.py --check
```

Builds refresh the copy automatically.

## Adding a comparison rule or an LLM provider

Documented here once the comparison and provider modules exist.

## Commits and pull requests

- One logical change per commit, about 200 changed lines at most (lock files
  excluded), tests in the same commit, every commit passes all checks.
- Messages follow Conventional Commits: `type(scope): subject`, imperative,
  lowercase, at most 72 characters. Types: `feat`, `fix`, `refactor`, `test`,
  `docs`, `ci`, `build`, `chore`, `perf`. Scopes: `python`, `spec`, `docs`,
  `ci`, later `js`.
- Footer `Refs: task NN` in every commit.
- No AI co-author trailers or AI attribution lines in commits or pull requests.
- A pull request that changes behavior, a flag, a config key or the output
  updates the docs and `CHANGELOG.md` in the same pull request.

## Releases

Each package is tagged separately: `py-v<version>` for Python, `js-v<version>`
for JS. Releases are made only by the maintainer.
