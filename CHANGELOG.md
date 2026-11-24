# Changelog

All notable changes are documented here, one section per package. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/). Release tags are `py-v*` for
the Python package and `js-v*` for the JS/TS package.

## Python package

### Unreleased

#### Added

- A GitHub Action (`github-action/`, docs/github-action.md) runs
  `didibreak check` on pull requests and keeps one comment up to date with
  the unexpected and unclear findings, skip counts and the run's cost.
  Inputs: the API key from a secret, provider, model, `max-cost`,
  `max-tokens`, `mode` (`report-only` or `fail-on-unexpected`) and
  `intent-source` (pull request text, commit messages only, or a fixed
  text). It runs only on `pull_request`, skips with a notice and passes
  when there is no key (pull requests from forks), shows untrusted text
  only in code blocks, stays under GitHub's comment size limit, and is
  pinned with the `py-v*` tags (the action installs the didibreak
  version released with its tag).
- `--no-commit-intent` (config key `no_commit_intent`) leaves the commit
  messages since `--base` out of the intent, so only `--intent` is used
  for labelling. For CI, where a pull request's author also writes its
  commit messages.
- The GitHub Action passes `--no-commit-intent` for `intent-source:
  fixed`, so no text from the pull request's author reaches the
  labelling; with a didibreak version without that flag it refuses to run
  in that mode.

#### Changed

- `docs/output-format.md` no longer names async functions and instance
  methods as skipped by design.

### 0.4.0 - 2026-11-23

**Highlights: instance methods are now checked, including the object's
state after the call.** Each case builds the instance from literal
constructor arguments, calls the method and compares the instance's
attributes as well as the result. **Constructor changes are reported**:
an instance built in one version only is a finding on `Class.__init__`,
and a changed `__init__` is checked itself. **Replies are capped**, so
runs cost less over their estimate when the model runs away (the worst
measured run went from 3.9 to 2.3 times its estimate).

#### Upgrading from 0.3.x

- **JSON report `schema_version` 2.** A consumer that requires
  `schema_version: 1` must accept 2. Version 2 only adds keys:
  `init_args` and `init_kwargs` on findings of instance methods and
  constructors, `state` (the instance's attributes) on their outcomes,
  and `summary.construction_dropped`, which is always present. A report
  without method findings only adds `summary.construction_dropped`
  (`docs/output-format.md`, `spec/report.schema.json`).

#### Added

- Instance methods are checked instead of skipped. For each case the LLM
  proposes constructor arguments as well as the call's arguments, as
  Python literals under the same rule; the instance is built from them
  (under the runtime I/O guard and the timeout) and the method is called
  on it. The instance's state after the call (`__dict__` and slots) is
  compared too, so a method that returns `None` but changes `self`
  differently is a finding. Reproducing tests build the instance and
  assert its state. A case whose instance cannot be built in either
  version is dropped and counted; when none is left the method is
  skipped (`construction failed: <type>` or `constructor changed: ...`).
  Properties, dunder methods other than `__init__` and methods of
  classes that do I/O while they are built stay skipped.
- A constructor that fails in one version only is a finding on
  `Class.__init__`, labelled against the intent like any other: for
  example `Order(0)` that the base built and the change now rejects. A
  changed `__init__` is checked itself by building the instance from
  constructor arguments; its outcome is the exception or the instance's
  state right after it was built. The reproducing test builds the
  instance (`pytest.raises` when the base raised, else type and state).
- When a case-generation reply has no valid case, the same request is
  sent once more if it fits `max_cost` and `max_tokens`.

#### Changed

- A case-generation reply is capped at 700 output tokens per requested
  case (8,400 for the default 12; at least 4,000, at most 16,000) instead
  of 16,000. Replies that reached 16,000 were runaway output, and with the
  retry they made some runs cost 4 to 6 times their estimate. Every
  request's cap also stays within what is left of `max_tokens` and
  `max_cost`.
- The skip reason `instance method` is gone; new reasons are `property`,
  `dunder method` (not for `__init__`), `construction failed: <type>`
  and `constructor changed: no constructor arguments work in both
  versions`.
- The JSON report is `schema_version: 2`. It only adds keys to version 1:
  `init_args` and `init_kwargs` on findings of instance methods, `state`
  (the instance's attributes after the call) on their outcomes, and
  `summary.construction_dropped`. A report without method findings has
  the same keys as before apart from that count (`docs/output-format.md`).
  The text report shows a `state before … → after …` line when the
  instance changed.

### 0.3.0 - 2026-11-22

**Highlight: `async def` functions are now checked.** Each case runs the
coroutine with `asyncio.run`, under the same timeout, comparison rules and
runtime I/O guard as other functions; async generators stay skipped. The
JSON report keeps `schema_version: 1`.

#### Added

- `async def` functions are checked instead of skipped. Each case runs the
  coroutine with `asyncio.run` in a new event loop, with the same timeout,
  seed and comparison rules as other functions, and the reproducing tests
  call it with `asyncio.run(...)` too. The runtime I/O guard stays on:
  a subprocess, a connection or a file change outside the temporary folder
  from inside a coroutine still skips the function with `blocked: <event>`.
  A function that changed between `def` and `async def` is not awaited in
  either version, so the change shows as a coroutine in the report.
- A GitHub issue template "Skipped or wrong finding": it asks for the
  didibreak version, the function's signature and a short excerpt, the
  skip reason or the finding, and what you expected instead.

#### Changed

- The skip reason `async function` is gone. Async generators are skipped
  as `async generator`, and the obvious-I/O list also covers network calls
  from coroutines (`asyncio.open_connection`, `asyncio.start_server`, ...)
  and async clients (`websockets`, `asyncpg`, `aiomysql`, `aiosqlite`,
  `aiofiles`, `motor`, `aioboto3`, `aiobotocore`).
- The README, the PyPI page and `docs/safety.md` no longer name a version
  in statements about the current release ("Currently skipped", "didibreak
  is alpha"), and the JavaScript / TypeScript package is described as
  "planned, not available yet". Recorded example output keeps the version
  it was recorded with.

### 0.2.0 - 2026-11-15

The cleanup from the code audit (`evaluation/audit-35a.md`, findings 7 and
9–12; prepared as 0.1.5, which was never tagged) and the safety and
robustness fixes from the pre-launch review
(`evaluation/review-prelaunch.md`, findings 1 to 14). The JSON report keeps
`schema_version: 1`.

#### Upgrading from 0.1.x

- **Runtime I/O guard.** A function that runs a command, reaches the
  network, loads native code or changes files outside its temporary folder
  while it runs, or while its module is imported, is now skipped with
  `blocked: <event>` (for example `blocked: os.system`) instead of being
  run. Such skips are by design: a run where every function is blocked
  exits 0 with "No function was checked" and `functions_checked: 0`
  (`docs/safety.md`).
- **Exit code 2 when nothing could be checked.** When functions were
  selected but none could be checked because of an error (provider
  unreachable, invalid replies, a cost or token limit, an import failure),
  `check` exits 2 (since 0.1.4; before, 0). An unexpected error inside
  didibreak now also exits 2 with an `internal error` line, not 1, so exit
  1 always means findings.
- **Stricter config validation**, with exit 2 before any request:
  `timeout` above 3600 seconds; `nan` or `inf` for `timeout`, `max_cost`
  and `prices` (since 0.1.4); an API key variable whose value is more than
  the key (a space, a line break, a non-printable character). A
  `--provider` flag that differs from the file's `provider` now discards
  the file's `base_url` and `api_key_env`; a file that sets them without
  `provider` counts as another provider, so add `provider` to it.
- **Environment scrub.** More credentials are removed from the environment
  of the code under test: names containing `PASS`, `APIKEY` or `API_KEY`,
  names ending in `_PAT`, `_PWD` or `_CREDENTIALS`, and URL or proxy
  variables that carry a password. Code that reads such a variable sees it
  missing. `TMPDIR`, `XDG_CACHE_HOME`, `MPLCONFIGDIR` and
  `NUMBA_CACHE_DIR` point into the temporary folder.

#### Added

- A runtime I/O guard in every process that runs your code: an audit hook
  (PEP 578), installed before your module is imported, stops commands and
  processes, network access, loading native code, and file changes outside
  the process's temporary folder. A function that tries one is skipped with
  `blocked: <event>` (for example `blocked: os.system`), never reported as
  a finding, and gets no reproducing test. It covers what the static I/O
  rules cannot see: `eval`, `exec`, `pickle.loads`, renamed functions,
  classes, decorators and other modules. It is defence in depth, not a
  sandbox: C extensions with their own I/O are not stopped
  (`docs/safety.md`).
- GitHub issue templates: a bug report that asks for the didibreak and
  Python versions, the OS, the exact command and the output (with API keys
  removed), a feature request, and links to the docs.

#### Changed

- The code under test gets its temporary folder as `TMPDIR` too.
- A module that writes a file outside that folder while it is imported is
  skipped with `blocked: open` instead of being run.
- `XDG_CACHE_HOME`, `MPLCONFIGDIR` and `NUMBA_CACHE_DIR` point into that
  temporary folder for the code under test, so a library that writes its
  cache while it is imported is run instead of skipped. `HOME` is not
  changed.
- Your existing Matplotlib font lists (`fontlist-*.json`) are copied into
  that `MPLCONFIGDIR`, so a module that imports `matplotlib.pyplot` is run
  instead of skipped with `blocked: subprocess.Popen`. Without a font list
  for the installed Matplotlib version it is still skipped
  (`docs/safety.md`).
- One rule checks case arguments everywhere (LLM replies, the case cache,
  the developer option `--cases-file` and the harness): Python literals of
  at most 2,000 characters, with usable keyword names. `--cases-file` now
  also rejects longer arguments and keyword names such as `class`, as LLM
  replies always did.
- Internal cleanup with no change to the output: dead code removed, stale
  comments rewritten, and the longest functions (`check`, the harness
  child start, the git change list, the report builder) split into named
  steps.
- AGENTS.md and CONTRIBUTING: never pipe a check through a command that
  hides its exit code (`| tail`); use `set -o pipefail`.

#### Fixed

- More credentials are removed from the environment of the code under
  test: names containing `PASS`, `APIKEY` or `API_KEY` (`DB_PASS`,
  `SMTP_PASSWD`, `OPENAI_APIKEY`), names ending with `_PAT` (`GH_PAT`), and
  proxy settings with a password (`HTTPS_PROXY=http://me:pw@proxy:8080`,
  lower-case names too). Before, a password in `DB_PASS` could reach the
  report, the reproducing test and the labelling request through a return
  value.
- `--provider openai` or `--provider anthropic` kept a `base_url` and
  `api_key_env` from `pyproject.toml` that were meant for another
  provider, so the API key was sent to that host. Any `--provider` that
  differs from the file's `provider` now discards both, as presets
  already did; `--base-url` on the command line still applies.
- `timeout` has a maximum of 3600 seconds. A larger value (`--timeout 1e9`)
  overflowed the timer: every case ended the process in both versions, no
  change was found and the run passed with exit 0. It is now rejected with
  exit 2.
- `max_tokens` and `max_cost` also stop a run when the server reports no
  token usage (no `usage` object, zeros or negative numbers). Such calls
  counted as 0 tokens, so the limits never applied and the report showed
  0 tokens. They now count an estimate from the size of the request and
  the reply, and a warning on stderr says so.
- Symbolic links that lead into the repository are no longer copied into
  the temporary copy the current version runs from, so code run from the
  copy cannot write the real files through them: absolute links into the
  repository, and relative links with enough `../` to reach the
  file-system root and come back. An absolute link that loops (points to
  itself or forms a cycle) is left out too. Other relative links and links
  outside the repository are still copied.
- The `didibreak: error:` and `didibreak: warning:` lines on stderr escape
  control characters like the text report does. A provider error message
  with terminal escape codes could clear the screen or change the
  terminal's title through the exit-2 line and the "model not found"
  message.
- An unexpected exception inside didibreak ends with exit code 2 and one
  line, `didibreak: error: internal error (...)`, that asks for a bug
  report (`-v` adds the traceback). Before, it left with a traceback and
  exit code 1, the code that means "findings". A `Retry-After: nan`
  header from a provider was one way to get there; it is now ignored.
- An argument with a comment (`2  # the smallest even prime`) is a valid
  literal, but pasted into the reproducing test it swallowed the rest of
  the line: the file had a syntax error and the tests of the other
  findings were lost with it. Accepted arguments are now stored in a
  normal form (no comments, standard spacing and quotes), which reports,
  reproducing tests and the cache all use.
- Returned strings and bytes have a size limit. A value longer than
  100,000 characters is compared by its length and SHA-256 digest instead
  of being stored, and a value with more than 1,000,000 characters of
  text in total is compared by type only. Before, one 40 MB return value
  cost the didibreak process about 230 MB of memory.
- An API key variable whose value has a space, a line break or a
  character outside printable ASCII is rejected before any request, with
  exit 2 and a message that names the variable and never shows the
  value. Before, a key with a trailing line break gave `llm unavailable`
  after three attempts, and the internal error text quoted the key.

### 0.1.4

Released when the tag `py-v0.1.4` is pushed. Safety and correctness fixes
from the code audit (`evaluation/audit-35a.md`). The JSON report keeps
`schema_version: 1`.

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
