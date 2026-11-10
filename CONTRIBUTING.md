# Contributing

## Repository layout

One repository, one folder per package, a shared contract:

| Path | Contents |
| --- | --- |
| `python/` | PyPI package `didibreak` (uv + hatchling, `src/` layout). |
| `js/` | npm package, added after Python 0.1.0. |
| `spec/` | Shared contract: JSON report schema, prompt templates, shared test cases. |
| `docs/` | User documentation for all packages (plain Markdown). |
| `evaluation/` | Real-repository evaluation for the release gate: plan, seeded patches, saved reports, hand labels, results (`python/scripts/evaluate.py`). |

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

To install the built wheel and sdist into fresh virtual environments and run
`didibreak --version`, `init-agents` and one `check` against a fake local
OpenAI-compatible server (no key, no cost; needs network for `httpx`):

```bash
python scripts/package_smoke.py dist
```

## Continuous integration

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Runs on changes in | What it does |
| --- | --- | --- |
| `python.yml` | every pull request; pushes to `main` that change `python/`, `spec/`, `LICENSE` | The four checks, build and package content check, on Linux with Python 3.11–3.13. macOS (not a required check): Python 3.11–3.13 on pull requests and pushes once the repository is public; while it is private, Python 3.13 on pushes to `main`, the weekly schedule (Mondays) and manual runs only. The steps live in `.github/actions/python-checks/`. |
| `spec.yml` | `spec/`, prompt-copy code | Report schema is valid JSON, a valid JSON Schema (draft 2020-12, checked with `check-jsonschema`) and has the expected structure; packaged prompts match `spec/prompts/`. |

### Required checks for `main`

Once the repository is public, the three Linux checks from `python.yml` are
required before a pull request can merge into `main`: `Linux / Python 3.11`,
`Linux / Python 3.12`, `Linux / Python 3.13`. The macOS jobs run on every pull
request too but are not required, so a macOS runner-capacity cancellation
never blocks a merge (owner decision 2026-11-10); look at a failed macOS run
before merging. The owner sets the rule once (repository settings → Branches,
or):

```bash
gh api -X PUT repos/changelia/didibreak/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {"context": "Linux / Python 3.11"},
      {"context": "Linux / Python 3.12"},
      {"context": "Linux / Python 3.13"}
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
```

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

## Running check without an LLM

`--cases-file PATH` is a hidden developer and testing option, not a user
feature: `didibreak check` takes the input cases from a JSON file instead of
asking the LLM, so the deterministic part (git, function detection, harness,
comparison) runs without any API key or cost. The format is the case
generation schema with a `function` key per case:

```json
{
  "cases": [
    {"function": "app/utils/phone.py::normalize_phone", "args": ["'995 555 12 34 56'"], "kwargs": {}, "rationale": "country code without plus"}
  ]
}
```

`args` and `kwargs` values are Python literals written as strings;
`kwargs` and `rationale` may be left out. A changed function without cases
in the file is listed as skipped (`no cases`). Example on the
`phone_regression` fixture (all three documented cases; real output):

```text
$ didibreak check --cases-file ../cases.json
didibreak 0.1.0.dev0 · working tree vs HEAD (9d74d2b028c7)
1 changed function(s) to check (0 new)
3 cases · 2 behavior changes · 0 flaky dropped
  UNCLEAR      app/utils/phone.py::normalize_phone('+1 202 555 0100')
               before '+99512025550100' → after '+12025550100'
               no intent was given (--intent or a commit message)
  UNCLEAR      app/utils/phone.py::normalize_phone('995 555 12 34 56')
               before '+995555123456' → after '+995995555123456'
               no intent was given (--intent or a commit message)
Reproducing tests: .didibreak/tests/test_normalize_phone.py
$ echo $?
1
```

Cases from a file are never labelled, so findings are `unclear`. The report
goes to stdout; add `--format json` for the JSON report
([output-format.md](docs/output-format.md)).
`tests/test_check_end_to_end.py` runs every fixture this way.

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

## Checking the OpenAI client with a real call

Tests use mocked transports only. To make one real call through didibreak's
OpenAI client, set `OPENAI_API_KEY` and run from `python/`:

```bash
uv run python scripts/llm_smoke.py [MODEL] [OUTPUT]
```

It writes the model, PASS or FAIL, token usage and the reply to
`/tmp/didibreak-client.txt` (or OUTPUT) and never writes the key. Exit code 0
is PASS, 1 a failed call, 2 missing settings (no request is sent).

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

### Python release procedure

`.github/workflows/release-python.yml` builds once, checks the package
contents, smoke-tests the wheel and the sdist on Linux and macOS
(`scripts/package_smoke.py`, Python 3.11) and uploads the same files with
PyPI trusted publishing. Uploads run only from commits on `main` and wait
for the owner's approval in the `testpypi` and `pypi` environments.

1. Merge a pull request that sets `__version__` in
   `python/src/didibreak/__init__.py` and moves the changelog entries into
   a section for that version.
2. TestPyPI: Actions → release-python → Run workflow on `main`, approve
   the `testpypi` deployment. Then, in an empty folder:

   ```bash
   python3 -m venv .venv && . .venv/bin/activate
   pip install --index-url https://test.pypi.org/simple/ \
       --extra-index-url https://pypi.org/simple/ didibreak==<version>
   didibreak --version
   ```

   A version can be uploaded to TestPyPI only once; if something is wrong
   after the upload, fix it and release the next version.
3. PyPI: tag the same commit and push the tag; approve the `pypi`
   deployment. The build fails if the tag does not match `__version__`.

   ```bash
   git tag -a py-v<version> -m "didibreak <version>" <commit on main>
   git push origin py-v<version>
   ```

4. Create the GitHub release from the tag with the changelog section as
   notes: `gh release create py-v<version> --title "didibreak <version>" --notes-file <notes>`.
