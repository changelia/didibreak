# Changelog

All notable changes are documented here, one section per package. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/). Release tags are `py-v*` for
the Python package and `js-v*` for the JS/TS package.

## Python package

### Unreleased

#### Fixed

- Safety: functions that run shell commands or processes (`os.system`,
  `os.popen`, `os.exec*`, `os.spawn*`, `pty`, ...), change files
  (`os.rename`, `os.makedirs`, `os.chmod`, `Path.rename`, ...) or use
  network and database clients (`http.client`, `smtplib`, `ftplib`,
  `psycopg`, `pymysql`, `redis`, `boto3`, ...) are now skipped as obvious
  I/O instead of being run with the LLM's inputs. The docs now say plainly
  that the rules are a heuristic and a container is the real isolation.
- `timeout`, `max_cost` and `prices` reject `nan` and `inf`, as flags and
  in `pyproject.toml` (exit code 2). `--timeout nan` used to hide every
  behavior change and exit 0, and `max_cost = nan` switched the cost limit
  off without a message.

- `max_tokens` and `max_cost` are checked again before the retry after an
  unusable reply and before the JSON-mode fallback request. Before, a
  cut-off reply and its retry could pass the limit by two full replies
  (123,000 tokens for a 20,000 limit in the audit).
- A return value whose dict keys or set elements raise in `__repr__` is
  now recorded as a normal return (`<repr failed: ...>`, compared by type)
  instead of a process crash (`didibreak.ProcessExited`), which also gave
  new functions a false finding.
- Safety: more credentials are removed from the environment of the code
  under test: names ending in `_PWD` or `_CREDENTIALS` (`MYSQL_PWD`,
  `GOOGLE_APPLICATION_CREDENTIALS`), and `*_URL`, `*_URI`, `*_DSN`
  variables whose URL carries a password (`postgres://user:pass@...`).
  A `DATABASE_URL` without a password is kept.
- The text report no longer passes terminal control characters from LLM
  text or your code's `repr`s to the terminal: they appear as `\xNN`, and
  line breaks inside a reason become spaces. The JSON report is unchanged.

#### Changed

- Each LLM request asks for at most 16,000 output tokens where the server
  documents the field: `max_completion_tokens` for OpenAI and OpenRouter,
  `max_tokens` for Anthropic (as before), Ollama and LM Studio. Other
  OpenAI-compatible servers get no such field.
- `check` exits with code 2 when changed functions were selected but none
  could be checked because of an error (provider unreachable, invalid
  replies, cost or token limit, import failure); the report is still
  printed. Before, such a run exited 0 although nothing was checked.
  Functions skipped by design (async, instance methods, generators,
  obvious I/O) are not errors: the run still exits 0, and the text report
  now says "No function was checked". The `init-agents` snippet tells
  agents to report `functions_checked: 0`.

### 0.1.3

Released when the tag `py-v0.1.3` is pushed. Simpler model switching. The
JSON report keeps `schema_version: 1`: `usage.cost_usd` could already be
`null`, and no field was added.

#### Added

- `--max-tokens` / `max_tokens` (default 200,000): a hard limit on input +
  output tokens per run, for every provider and model. It is checked before
  each request like `max_cost`; functions after the limit are skipped with
  the reason `token limit`, and intent labelling that would exceed it leaves
  the findings `unclear`. Because it is checked before each request, a
  single request can go past the limit by the size of its own reply.
- Provider presets `openrouter`, `ollama` and `lmstudio` for `provider` /
  `--provider`. They use the OpenAI-compatible client and fill in
  `base_url` and `api_key_env` (`OPENROUTER_API_KEY`; no key for the two
  local servers); `model` is required. A `base_url` or `api_key_env` you
  set at the same level as the preset, or higher, replaces the preset's
  value.
- A preset given as `--provider` discards `base_url` and `api_key_env` from
  `pyproject.toml`, so `--provider ollama` never uses an OpenRouter URL or
  key configured there.
- The README "Change the model" section uses the presets; the prices
  block is now optional and only adds the cost and the `max_cost` limit.

#### Changed

- A remote model without a known price no longer stops `check` with exit
  code 2: it runs with a warning that `max_cost` is not enforced and
  `max_tokens` still applies. The estimate and the usage line say
  `cost unknown`, and the JSON report has `"cost_usd": null` (already
  allowed by schema version 1). Local models still cost 0.

#### Fixed

- On Windows, `didibreak check` and `didibreak init-agents` now stop at
  once with exit code 2 and a one-line message that Windows is not
  supported (Linux and macOS are), as the design promised. Before, there
  was no platform check.
- `--help` and `--version` still work on Windows: they run no user code.

### 0.1.2

Released when the tag `py-v0.1.2` is pushed. No change to what `didibreak`
does; documentation only.

#### Changed

- README and the PyPI page say what didibreak is and is not: an extra
  check next to your tests, not a production safety net; it finds behavior
  changes on the inputs it generates and cannot prove that no other input
  changed.
- README, the PyPI page and `docs/safety.md` recommend running didibreak
  inside a container or a CI job for code you did not write (external pull
  requests, unattended agents).
- README and the PyPI page have a "Change the model" section with three
  setups that work with 0.1.x: another OpenAI model with its `prices`
  entry, OpenRouter, and a local Ollama server. It explains why a paid
  model without a price stops with exit code 2.
- The remaining examples recorded with a development build
  (`docs/output-format.md`, `docs/providers-and-costs.md`,
  `CONTRIBUTING.md`) are re-recorded with didibreak 0.1.1 from PyPI.

### 0.1.1

Released when the tag `py-v0.1.1` is pushed. No change to what `didibreak`
does; documentation and project upkeep after the first release.

#### Changed

- README: what didibreak works well on and what 0.1 skips (async
  functions, instance methods, generators, obvious I/O, typical FastAPI and
  Django handlers), a line that it runs your changed functions (see
  `docs/safety.md`), PyPI, CI and license badges.
- The PyPI page shows a real example run.
- README and Getting started examples re-recorded with didibreak 0.1.0
  from PyPI.
- `AGENTS.md` and `CLAUDE.md` give every contributor's AI agent the
  project rules (CONTRIBUTING.md, docs/, checks, commit rules) without any
  private links.

#### Fixed

- The package smoke test (`scripts/package_smoke.py`) no longer blocks for
  minutes when its local fake provider stalls: each command has a 60 s
  limit. The test suite dumps every thread's stack when a test runs over
  5 minutes.
- Every CI and release job has a time limit; only the Linux checks are
  required for `main`.

### 0.1.0 - 2026-11-10

First release.

#### Added

- `didibreak check`: finds the Python functions changed between `--base`
  (default `HEAD`) and the working tree, asks an LLM for literal input
  cases, runs the old and the new version of each function on them in
  separate processes, and reports where the outcomes differ.
- Supported functions: module-level functions, `@staticmethod` and
  `@classmethod` methods. Async functions, instance methods, generators and
  functions with obvious I/O are skipped with a reason; so are modules that
  cannot be imported, before any LLM request.
- Comparison rules: two runs per version (flaky cases dropped), float
  tolerance, exception types, raise vs return, timeouts, type-only
  comparison with low confidence for values that cannot be compared, new
  functions (`new_function`, never changes the exit code).
- Intent labels: `--intent` and the commit messages since `--base` label
  each finding `expected`, `unexpected` or `unclear`; intent never hides a
  finding. Findings whose inputs contradict simple type annotations are
  dropped and counted.
- One refinement round (`refine_rounds`) for functions whose cases showed
  no difference.
- Text report and JSON report (`--format json`, `schema_version: 1`,
  `spec/report.schema.json`); exit codes 0 / 1 / 2 / 130 and `--fail-on`.
- Reproducing pytest files in `.didibreak/tests/` for `unexpected` and
  `unclear` findings; the output folder ignores itself.
- Providers: OpenAI and any OpenAI-compatible API (OpenRouter, Ollama, LM
  Studio) and Anthropic (experimental, not live-verified). Default models
  `gpt-6-luna` and `claude-haiku-5-5`. The user's own API key; no telemetry.
  `httpx` is the only runtime dependency.
- Cost control: an estimate and a confirmation before the first request,
  the `max_cost` limit (default $0.50), actual tokens and cost after the
  run, built-in prices and a `prices` setting, and a case cache.
- Safety: the working tree is never executed (temporary worktree and copy),
  credential-like environment variables are removed, LLM output is only
  ever parsed with `ast.literal_eval`, never executed.
- `didibreak init-agents` prints an `AGENTS.md` / `CLAUDE.md` snippet for
  AI coding agents; it never edits files.
- Configuration in `[tool.didibreak]` of `pyproject.toml`; every key has a
  CLI flag except `exclude`, `api_key_env`, `prices` and `temperature`.
- Documentation in `docs/`: getting started, how it works, configuration,
  output format, AI agents, providers and costs, safety, limitations.
- Measured on seven pure-Python libraries chosen for literal-friendly
  functions (model labels; application code may score lower): 87% of
  `unexpected` findings were real behavior changes (`evaluation/README.md`).

#### Known limitations

- Linux and macOS only. Inputs are Python literals, so functions that need
  objects get no useful cases. See `docs/limitations.md`.

## JS/TS package

### Unreleased

Not started; follows Python 0.1.0.
