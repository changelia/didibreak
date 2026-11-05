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
ruff, mypy), copies `spec/prompts/` into `src/didibreak/prompts/` and the root
`LICENSE` into `python/LICENSE`. Both copies are git-ignored.

## Checks

Run from `python/`; every commit must pass all of them:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Configuration lives in `python/pyproject.toml`:

- Ruff rules `E`, `F`, `W`, `I`, `B`, `UP`, `SIM`, `RUF`, `D` (Google
  docstring convention); tests are exempt from the missing-docstring rules.
- mypy in strict mode for Python 3.11.
- pytest with strict markers and config.

To check the built packages the same way CI does:

```bash
uv build
uv run python scripts/check_dist.py dist
```

## Continuous integration

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Runs on changes in | What it does |
| --- | --- | --- |
| `python.yml` | `python/`, `spec/`, `LICENSE` | The four checks, build and package content check. Pull requests: Linux, Python 3.11–3.13. Pushes to `main`, a weekly schedule (Mondays) and manual runs: macOS, Python 3.13 (pushes and manual runs also run Linux). The steps live in `.github/actions/python-checks/`. |
| `spec.yml` | `spec/`, prompt-copy code | Report schema is valid JSON, a valid JSON Schema (draft 2020-12, checked with `check-jsonschema`) and has the expected structure; packaged prompts match `spec/prompts/`. |

`js.yml` is added together with the JS package. Pull requests use the template
in `.github/pull_request_template.md`, which carries the Definition of Done.

## Prompt templates

Edit prompts only in `spec/prompts/`. After editing, refresh the package copy
and confirm it matches:

```bash
cd python
uv run python scripts/sync_prompts.py
uv run python scripts/sync_prompts.py --check
```

Builds refresh the copy automatically.

## Fixture repositories

`python/tests/fixtures/<case>/` holds small before/after code samples with
known behavior changes, used by tests of every stage:

- `before/` is committed as the base version, `after/` is left as the
  uncommitted working tree (`tests/fixture_repos.py`,
  `build_fixture_repository`);
- `expected.json` documents what didibreak should report: changed and skipped
  functions, findings with their outcomes, cases that must not produce a
  finding (for a new function: cases that return or raise an exception type
  the function raises itself), and flaky functions.
  `tests/test_fixture_repos.py` runs both versions to check that every
  documented outcome is true; `tests/test_compare_fixtures.py` runs every case
  through the harness and the comparison rules.

To add a case, create the three entries and run the tests. Fixture code is
excluded from ruff because it is sample user code.

## Adding a comparison rule

Comparison rules live in `python/src/didibreak/compare.py` and are pure
functions over harness outcomes:

1. Write the rule in `difference()` (two outcomes of one case) or in
   `compare_cases()` (dropping cases, new functions). Name any threshold as a
   module constant.
2. Add a unit test named after the behavior to
   `python/tests/test_compare_rules.py`.
3. If a fixture in `python/tests/fixtures/` shows the rule, update its
   `expected.json`; `test_compare_fixtures.py` runs every fixture through the
   harness and the rules.
4. Update the rule table in `docs/how-it-works.md`.

## Adding an LLM provider

Documented here once the provider modules exist.

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
