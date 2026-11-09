# Changelog

All notable changes are documented here, one section per package. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/). Release tags are `py-v*` for
the Python package and `js-v*` for the JS/TS package.

## Python package

### Unreleased

#### Added

- Package skeleton: `didibreak --version` and `python -m didibreak --version`.
- The MIT license text is included in the wheel and sdist.
- `didibreak check` with all flags and `[tool.didibreak]` config keys, validation
  errors with exit code 2, and exit codes 0/1/2 (the analysis is not implemented
  yet, so `check` reports no findings).
- `didibreak init-agents` prints the agent snippet.
- `didibreak check` resolves `--base` and finds changed Python files, including
  untracked ones, skipping the default exclusions and `exclude` patterns.
- Relative `output_dir` and `python` paths are resolved against the
  `pyproject.toml` folder (config file) or the current directory (flags).
- `didibreak check` detects changed and new functions (formatting, comments
  and docstrings are ignored), reports files it cannot parse, applies
  `max_functions`, and shows excluded files; `-v` lists them.
- A `python` value without `/` is looked up on `PATH`.
- Async functions, instance methods, generators and functions with obvious
  I/O are skipped with a reason; `-v` lists them.
- The obvious I/O rule resolves imports and aliases, follows calls to
  functions in the same module, covers more file, network and database
  calls, and applies to both the base and the current version.
- The import root is the folder of the nearest `pyproject.toml` (or its
  `src/`).
- Execution harness (not used by `check` yet): runs cases against one
  version of a function in separate processes, twice each, with per-case
  timeouts, fixed seeds and credentials removed from the environment.
- Subclasses of builtin types (`namedtuple`, `OrderedDict`, `IntEnum`, ...)
  are compared by value through their base; `Enum` members by class and
  name.
- Comparison rules (not used by `check` yet): flaky cases dropped, float
  tolerance, exception types, raise vs return, timeouts, type-only
  comparison with low confidence, new functions; deterministic finding ids.
- New functions: exception types raised by an explicit `raise` in the
  function or its same-module callees are not reported.
- `didibreak check` runs the changed functions on both versions and lists
  behavior changes when cases come from the hidden developer option
  `--cases-file` (cases from the LLM follow). The current version runs from a
  temporary copy of the working tree. Ctrl-C exits with code 130.
- `new_function` findings make the run exit 1 with the default
  `--fail-on unclear` (not with `--fail-on unexpected`).
- LLM clients for OpenAI-compatible APIs and Anthropic (not used by `check`
  yet), with retries, a JSON-mode fallback and default models `gpt-6-luna`
  and `claude-haiku-5-5`. `httpx` is the one runtime dependency.
- `check` exits with code 2 when the LLM provider, model or API key is
  missing and an LLM would be needed. Without a `provider` setting, the
  provider is taken from the one API key variable that is set.
- Config-only key `temperature`; without it no temperature is sent.
- `check` asks the LLM for input cases (versioned prompt
  `case_generation.md`), keeps only Python-literal, distinct cases, counts
  invalid ones, skips a function after two unusable replies, and runs the
  comparison with them. No cost estimate or limit yet.
- A request the provider rejects for a reason other than the key or the
  model (HTTP 4xx except 401, 403, 404) skips only that function.
- Cost control: estimate before the first request with a confirmation
  question on a terminal (`--yes` to skip), the `max_cost` limit (`cost
  limit` skip reason), actual tokens and cost after the run, built-in prices
  for the default models and a `prices` setting for others.
- Generated cases are cached in `.didibreak/cache/cases/`; `--no-cache`
  ignores the cache.
- A model without a known price exits with code 2 and a hint to add a
  `prices` entry; models on `localhost` / `127.0.0.1` cost 0 ("local").
- Intent labels: with `--intent` (and the messages of the commits since
  `--base`) one LLM request labels every finding `expected`,
  `unexpected` or `unclear` with a reason; without an intent findings are
  `unclear`. The exit code follows the labels.
- Refinement: a function whose cases found no difference gets up to
  `refine_rounds` (default 1) more rounds of LLM cases, built from the cases
  already tried and their results; counted in the estimate and the cost
  limit, and cached per round.
- Text and JSON reports on stdout: the text report groups findings
  `UNEXPECTED`, `UNCLEAR`, `EXPECTED`, `NEW-FUNCTION`, lists skipped
  functions with reasons and ends with the LLM usage line; `--format json`
  writes one report (`schema_version: 1`, `spec/report.schema.json`) with a
  stable key order, and the estimate goes to stderr. See
  `docs/output-format.md`.
- Reproducing pytest files: `check` writes one test file per function to
  `.didibreak/tests/`, one test per finding asserting the base behavior, so
  it passes on the base and fails on the change. Findings labelled
  `expected` get no test, so an agent is never pushed to undo an intended
  change. `test_file` in the JSON report and a `Reproducing tests:` line in
  the text report point to the file; the generated `conftest.py` sets
  `TZ=UTC` and seeds `random` like the harness.
- `docs/ai-agents.md`: where to put the `init-agents` snippet for Claude
  Code, Codex and Cursor (not verified with any agent yet), the check loop,
  what to do per label, and running reproducing tests only for
  `unexpected` and `unclear` findings.
- The `init-agents` snippet also says what to do with `new_function`
  findings, that exit code 2 is a setup problem to report, and to stop
  after 3 check rounds.
- Findings whose inputs contradict the function's simple type annotations
  (for example `bytes` for a `str` parameter) are dropped and counted in
  `summary.type_mismatch_dropped`; the JSON report is now
  `schema_version: 2`.

## JS/TS package

### Unreleased

Not started; follows Python 0.1.0.
