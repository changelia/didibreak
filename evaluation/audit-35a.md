# Code audit 35a (before launch)

Audit of `python/src/didibreak` at `ef71ad4` (main, 0.1.3 merged and not
tagged), 2026-11-11. This is a report only: no product code was changed.
The owner chooses which findings task 35b fixes.

**Reviewer note.** Task 35 asks for a fresh session. This audit ran in the
same Claude Code session that wrote task 34: the `max_tokens` budget
(`pipeline.Budget.refusal` / `allows`), unpriced runs, the presets in
`config.py` / `llm/__init__.py` and the Windows check in `cli.main`. Those
parts were read with extra care, but the review of them is not independent.
The rest of the code was written in earlier sessions.

## Method

- Every module was read, largest first. That includes `_harness_child.py`
  (the code that runs inside the child process) and `harness.py`.
- Coverage was measured once with coverage.py 7.10.7, run through `uvx` with
  the project's locked test dependencies. Coverage is not a project
  dependency.
- Dead code was checked with `uvx vulture@2.14 src --min-confidence 60`, and
  every hit was confirmed with `grep`.
- A finding is **CONFIRMED** only if it was reproduced. The commands are in
  the finding. The others are marked DESIGN WEAKNESS, POTENTIAL RISK or
  READABILITY.
- The output-cap question from the task 34 review is answered in its own
  section, with provider documentation checked on 2026-11-11.

## Summary

| # | Category | Finding | Severity |
| --- | --- | --- | --- |
| 1 | CONFIRMED BUG | The obvious-I/O rules miss command execution (`os.system`, `os.popen`), most file-system changes, and network or database clients. Such functions are run with LLM inputs | High |
| 2 | CONFIRMED BUG | `timeout` and `max_cost` accept `nan` and `inf`. `timeout = nan` hides every behavior change and exits 0; `max_cost = nan` turns the cost limit off | High |
| 3 | DESIGN WEAKNESS | A run that checked 0 functions exits 0 (provider down, cost or token limit, every function skipped), so an AI agent reads it as "no regressions" | Medium |
| 4 | DESIGN WEAKNESS | The budget is checked once per `complete_json`, but one call can send up to four requests (JSON-mode fallback plus the invalid-reply retry), and no output limit is sent. Reproduced: 123,000 tokens used with `max_tokens = 20,000` | Medium |
| 5 | CONFIRMED BUG | A return value whose dict keys or set elements have a raising `__repr__` crashes the child. A normal return is then recorded as `didibreak.ProcessExited` | Low–medium |
| 6 | POTENTIAL RISK | Credentials in variables such as `DATABASE_URL`, `REDIS_URL`, `*_DSN`, `MYSQL_PWD` and `*_CREDENTIALS` reach the user's code | Medium (with #1) |
| 7 | POTENTIAL RISK | Symbolic links in the working-tree copy can point back into the user's repository, so code run "from the copy" can write the real tree | Low |
| 8 | POTENTIAL RISK | LLM text (`reason`) and user `repr`s are printed to the terminal unfiltered (terminal escape sequences) | Low |
| 9 | READABILITY | Dead code: `gitdiff.commit_message`, `Budget.allows`, `config.PATH_KEYS`; leftover `price` / `max_cost` parameters of `generate_cases` | Low |
| 10 | READABILITY | Stale comments that describe an earlier state (`pipeline.py`, `anthropic.py`) | Low |
| 11 | READABILITY | Four literal validators with different rules; argument formatting written four times | Low |
| 12 | READABILITY | Long functions: `cli._run_check` (86 lines), `harness._start_child` (49), `cli._build_report` (44), `gitdiff.changed_python_files` (41) | Low |

No finding breaks the key invariants:

- the API key never appears in errors;
- LLM output is never executed;
- didibreak never writes outside `.didibreak/`.

Findings 1 and 6 touch the safety boundary of running the user's own code
with LLM inputs. That boundary is a documented heuristic, not a sandbox.

## Findings

### 1. CONFIRMED BUG: obvious-I/O rules miss command execution and common I/O

- **Where:** `python/src/didibreak/testability.py:16-59` (`OBVIOUS_IO`).
- **Trigger:** a changed function that calls `os.system`, `os.popen`,
  `os.exec*` or `os.spawn*`. The same happens for:
  - file changes: `os.rename`, `os.replace`, `os.makedirs`, `os.mkdir`,
    `os.chmod`, `os.truncate`, `Path.rename`, `Path.replace`, `Path.chmod`,
    `Path.symlink_to`;
  - network or mail: `http.client`, `urllib3`, `smtplib`, `ftplib`;
  - database drivers: `psycopg`, `pymysql`, `sqlalchemy.create_engine`,
    `redis`.

  The rules list only `open`, `os.remove` / `unlink` / `rmdir`,
  `shutil.rmtree` / `move` / `copy*`, `urllib.request.*`,
  `sqlite3.connect`, a few `Path` methods, the modules `subprocess`,
  `requests`, `httpx` and `socket`, and `session.commit`-style calls.
- **Reproduction** (rule level):

  ```text
  $ uv run python -c "from didibreak.testability import module_context, skip_reason; ..."
  os.system    -> None      os.popen  -> None      os.rename -> None
  os.makedirs  -> None      Path.rename -> None    http.client -> None
  smtplib      -> None      shutil.rmtree -> obvious I/O: shutil.rmtree (control)
  ```

  **Reproduction** (end to end, no LLM). `app/run.py` contains
  `def notify(name): os.system("touch " + os.environ["MARK_DIR"] + "/ran_" + name)`.
  The return value was changed and the change left uncommitted:

  ```text
  $ MARK_DIR=$PWD/marks didibreak check --cases-file cases.json --yes
  1 changed function(s) to check (0 new)
  1 cases · 1 behavior changes · 0 flaky dropped
    UNCLEAR      app/run.py::notify('x')
  exit 1
  $ ls marks
  ran_x
  ```

  The shell command ran, with a string argument supplied as a case.
- **Impact:** in a normal run, the arguments come from the LLM. A function
  that builds a shell command or a path from its arguments is executed with
  edge-case inputs such as unusual strings, `..` and empty values.
  `limitations.md` says obvious I/O is skipped, but users would expect
  command execution to count as obvious. This is the most important
  safety-boundary gap before launch.
- **Minimal fix:** add these entries to `OBVIOUS_IO`:
  - `calls`: `os.system`, `os.popen`, `os.exec*`, `os.spawn*`, `os.kill`,
    `os.rename`, `os.replace`, `os.makedirs`, `os.mkdir`, `os.chmod`,
    `os.chown`, `os.truncate`, `os.symlink`, `os.link`, `shutil.chown`,
    `sqlalchemy.create_engine`;
  - `modules`: `http`, `urllib3`, `aiohttp`, `smtplib`, `ftplib`,
    `psycopg`, `psycopg2`, `pymysql`, `redis`, `boto3`;
  - `path_methods`: `rename`, `replace`, `chmod`, `symlink_to`,
    `hardlink_to`.

  Update `docs/limitations.md` to match. It stays a heuristic: the docs
  must keep saying so.
- **Regression test:** a parametrized `skip_reason` test with one function
  per new entry, each expected to return `obvious I/O: <name>`. Add one
  `check --cases-file` test showing that a function calling `os.system`
  is skipped and never run (a marker file is not created).

### 2. CONFIRMED BUG: `nan` and `inf` accepted for `timeout` and `max_cost`

- **Where:** `python/src/didibreak/config.py:117-122` (`_positive_number`
  only checks `value <= 0`, which is False for `nan`). The effect shows in
  `python/src/didibreak/_harness_child.py:231` (`signal.setitimer`) and
  `python/src/didibreak/pipeline.py:497-500` (`_over_max_cost`).
- **Trigger:** `--timeout nan`, or `timeout = nan` / `max_cost = nan` in
  `pyproject.toml` (TOML allows `nan` and `inf`). Also `--max-cost nan` and
  `inf` values.
- **Reproduction** (the same repository as in finding 1, which has one real
  behavior change):

  ```text
  $ didibreak check --cases-file cases.json --timeout nan --format json; echo $?
  0                                   # findings: 0, cases_run: 1
  $ python -c "import signal; signal.setitimer(signal.ITIMER_REAL, float('nan'))"
  ValueError: Invalid value NaN (not a number)
  $ python -c "from didibreak.config import validate; print(validate('max_cost', float('nan')))"
  nan
  # Budget(price, max_cost=nan).refusal(<10M-character prompt>) -> None (no cost limit)
  ```

  `setitimer` raises before each case. The child exits 1, and both
  versions record `didibreak.ProcessExited`. The comparison sees the same
  outcome on both sides, so the real change disappears and the run exits 0.
- **Impact:**
  - With `timeout = nan`, every run silently passes. An AI agent would
    accept a regression.
  - With `max_cost = nan`, the cost limit is off without any message.
  - With `timeout = inf`, the parent waits forever on a function that never
    returns.
- **Minimal fix:** in `_positive_number`, reject values that are not finite
  (`math.isfinite`), with the message `"{key} must be a finite number
  greater than 0"`.
- **Regression test:** extend
  `test_invalid_values_are_rejected_with_the_rule` with `nan` and `inf` for
  `timeout` and `max_cost`. Add a CLI test showing that `--timeout nan`
  exits 2.

### 3. DESIGN WEAKNESS: exit 0 when no function was checked

- **Where:** `python/src/didibreak/cli.py:91-108` (`exit_code_for` looks only
  at labels) and the end of `_run_check` (`cli.py:705-708`). Documented in
  Detailed Design §10: `llm unavailable` → "1 if findings else 0".
- **Trigger:**
  - the provider is down or unreachable;
  - the cost or token limit is reached before the first request;
  - every changed function is skipped by an import failure or a limit.
- **Reproduction** (no server on port 11434):

  ```text
  $ didibreak check --provider ollama --model llama3.2 --format json; echo $?
  0
  summary.functions_checked = 0
  summary.skipped = [{"function": "app/run.py::notify", "reason": "llm unavailable"}]
  ```

- **Impact:** the main users are AI agents following the
  `init-agents` snippet. The snippet only says what to do with
  `unexpected` and `unclear` findings, and that "Exit code 2 means a setup
  problem", so a run that checked nothing reads as "no regressions". The
  JSON shows `functions_checked: 0`, but the snippet does not tell the
  agent to look at it.
- **Minimal fix** (owner decision needed). Options:
  - (a) exit 2 with a message when testable functions existed but none was
    checked because of `llm unavailable`, `cost limit` or `token limit`;
  - (b) keep exit 0, but add one sentence to the agent snippet and
    `ai-agents.md`: "if `functions_checked` is 0, report it".

  Option (a) matches the snippet's meaning of exit 2.
- **Regression test:** a fake provider that always returns 503, then
  assert the chosen exit code and message. Repeat with
  `--max-tokens 1`.

### 4. DESIGN WEAKNESS: the budget is not checked for retries, and no output limit is sent

- **Where:**
  - `python/src/didibreak/llm/common.py:357-386`
    (`complete_with_one_retry`: two attempts without a budget check);
  - `python/src/didibreak/llm/openai_compat.py:197-218` (JSON-mode fallback:
    one more request);
  - `python/src/didibreak/llm/openai_compat.py:88-131` (no output limit in
    the payload);
  - `python/src/didibreak/pipeline.py:475-500` (`Budget.refusal` runs once
    per function).
- **Trigger:** a reply cut off at the model's output limit
  (`finish_reason: length`), or any reply that is not valid JSON. The client
  then sends a second request without asking the budget.
- **Reproduction** (mock transport: every reply is cut off and reports
  60,000 output tokens):

  ```text
  Budget(None, None, 12, max_tokens=20_000); generate_cases(client, [f, g], ...)
  requests sent: 2 | any output cap in payload: False
  tokens used: 123000 vs max_tokens 20000
  skips: [('f', 'invalid llm response'), ('g', 'token limit')]
  ```

- **Impact:** `max_tokens` and `max_cost` can be exceeded by up to two full
  replies at the model's largest output (four requests if the JSON-mode
  fallback also triggers). This matters most for unpriced models, where
  `max_tokens` is the only limit since 0.1.3. See the next section for the
  numbers and the recommendation.
- **Minimal fix:** see the recommendation below:
  - check the budget before the second attempt;
  - send a per-request output limit where the parameter is documented.
- **Regression test:** the reproduction above as a unit test. Assert one
  request only, and that the skip reason of the function is `token limit`
  after its first oversized reply.

### 5. CONFIRMED BUG: a raising `__repr__` on dict keys or set elements crashes the child

- **Where:** `python/src/didibreak/_harness_child.py:89` and `:97` (sort by
  `repr`, which runs user code). `normalize()` at `:139-142` catches only
  `_Unrepresentable` and `RecursionError`.
- **Trigger:** the function returns a dict whose keys, or a set whose
  elements, are user objects whose `__repr__` raises.
- **Reproduction:**

  ```text
  # m.py: class Key: __repr__ raises RuntimeError;  def f(x): return {Key(): x}
  run_cases(Target(tree, tree, "m", "f"), [Case(("1",)), Case(("2",))], ...)
  exception didibreak.ProcessExited <the process exited with code 1 during the case>
  exception didibreak.ProcessExited <the process exited with code 1 during the case>
  ```

- **Impact:**
  - A normal return is reported as a process crash.
  - For a new function, `ProcessExited` is always a `new_function`
    finding, so it is a false finding.
  - Each case also starts a new child process, which is slower.

  Rare, but wrong output.
- **Minimal fix:** in `normalize()`, catch `Exception` as well (except
  `CaseTimeout`, which is a BaseException) and return None. The value is
  then compared by type, with low confidence.
- **Regression test:** the reproduction as a harness test. The outcome
  kind is `return`, with the dict type name and no value.

### 6. POTENTIAL RISK: credential URLs reach the user's code

- **Where:** `python/src/didibreak/harness.py:33-34` (`SECRET_SUFFIXES`,
  `SECRET_WORDS`), documented in `docs/safety.md:88-96`.
- **Trigger:** variables that carry credentials without a matching name.
  `child_environment` keeps `DATABASE_URL`, `REDIS_URL`, `SENTRY_DSN`,
  `MYSQL_PWD`, `GOOGLE_APPLICATION_CREDENTIALS` and `NPM_AUTH` (checked).
  It removes `*_KEY`, `*TOKEN*`, `*SECRET*` and `*PASSWORD*`.
- **Impact:** together with finding 1 (database drivers are not detected),
  a changed function that opens `DATABASE_URL` can run with LLM inputs
  against whatever database the shell points at. It matches the
  documented rule, so this is a risk, not a bug.
- **Minimal fix:** also remove names ending in `_URL` or `_DSN` when the
  value contains `@` (credentials in the URL), names containing
  `CREDENTIAL` or `AUTH`, and `*_PWD`. Update `safety.md`.
- **Regression test:** extend the `child_environment` test with these names
  and with a credential-free URL that is kept.

### 7. POTENTIAL RISK: symbolic links in the working-tree copy

- **Where:** `python/src/didibreak/gitdiff.py:401`
  (`copy2(..., follow_symlinks=False)`).
- **Trigger:** a tracked symbolic link with an absolute target, or a
  relative target that leaves the copy (`../../data`).
- **Impact:** the current version runs "from a temporary copy". Writes
  through such a link reach the original files. Not reproduced: it needs a
  function that writes, and the I/O rules already skip most writes (see
  finding 1 for the gaps).
- **Minimal fix:** say so in `safety.md`. Optionally, skip links whose
  resolved target is outside the copy and list them in the header like
  excluded files.
- **Regression test:** a fixture repository with an absolute link. Assert
  the chosen behavior.

### 8. POTENTIAL RISK: unfiltered text on the terminal

- **Where:** `python/src/didibreak/report/text.py:83-87` (the `reason` from
  the LLM and the user's `repr` are printed as they are).
- **Trigger:** an LLM reason, or a custom `__repr__`, that contains terminal
  escape sequences (`\x1b[...`).
- **Impact:** low. The output can change the terminal's display or title.
  The LLM is not fully trusted (Spec: "LLM output is data").
- **Minimal fix:** replace control characters except newline in `reason`
  and `repr` before printing the text report.
- **Regression test:** a report sample with `\x1b[2J` in the reason. The
  text output contains no ESC character.

### 9. READABILITY: dead code

- **Where and impact:**
  - `python/src/didibreak/gitdiff.py:425` `commit_message()` is never
    called. The pipeline uses `commit_messages()`.
  - `python/src/didibreak/pipeline.py:502` `Budget.allows()` is never
    called since `refusal()` replaced it (task 34).
  - `python/src/didibreak/config.py:212` `PATH_KEYS` is only mentioned in
    a docstring. `resolve_paths` names the keys itself.
  - `python/src/didibreak/pipeline.py:532-570`: the `price` / `max_cost`
    parameters of `generate_cases` are used only by tests. The session
    always passes `budget`.
- **Minimal fix:** remove them. Change the tests to build a `Budget`.
- **Regression test:** none needed. Existing tests cover the remaining
  paths.

### 10. READABILITY: stale comments

- **Where:**
  - `python/src/didibreak/pipeline.py:5-6` ("Cases come from the hidden
    developer option `--cases-file` until LLM case generation exists (task
    14)").
  - `python/src/didibreak/pipeline.py:57-58` ("Until intent labelling
    exists (task 17)…").
  - `python/src/didibreak/llm/anthropic.py:3-5` ("required before release,
    task 23"; it is released and still not live-verified).
- **Impact:** a new reader is told features are missing that exist.
- **Minimal fix:** rewrite the three comments to the current state.
- **Regression test:** none.

### 11. READABILITY: duplicated logic

- **Where:**
  - The literal check exists four times, with different rules:
    `cases.is_literal` (length limit), `pipeline._case` (`--cases-file`:
    no length limit and no keyword-name check), `cache._case_from_json`
    (identifier check without the `keyword.iskeyword` check), and
    `harness._check_literals`.
  - The `name(args, k=v)` formatting exists four times:
    `cases.describe_call`, `report/text.py:77`, `pytest_writer._call` and
    `pytest_writer.finding_call`.
  - `_int()` is written once in each of `llm/openai_compat.py:36` and
    `llm/anthropic.py:38`.
  - `build_messages` and `build_refinement_messages` repeat the same
    substitution.
  - `report/pytest_writer.py:23` imports `tree_import_root` from
    `pipeline`, so the report layer depends on orchestration.
  - `cli.py` calls `repository_root` twice (`:228` and `:635`).
- **Impact:** the validators can drift apart, which matters for the
  "LLM output is data" invariant. For example, `--cases-file` accepts a
  keyword argument named `class`, which the LLM path rejects.
- **Minimal fix:**
  - one `validate_case(args, kwargs) -> Case | None` in `cases.py`, used by
    all four places;
  - one `format_call()`;
  - `_int` moved to `llm/common.py`;
  - `tree_import_root` moved to `functions.py`.
- **Regression test:** a parametrized test feeding the same bad cases
  (keyword name `class`, a 3,000-character string, `__import__('os')`) to
  every entry point, with the same result everywhere.

### 12. READABILITY: long functions

- **Where:**
  - `python/src/didibreak/cli.py:623` `_run_check` (86 lines);
  - `python/src/didibreak/harness.py:196` `_start_child` (49);
  - `python/src/didibreak/cli.py:534` `_build_report` (44);
  - `python/src/didibreak/gitdiff.py:202` `changed_python_files` (41).

  The project guideline is about 40 lines.
- **Impact:** `_run_check` mixes config loading, the header, the cases-file
  path, the LLM path, test writing and the exit code. It is the hardest
  function to change safely, for example for finding 3.
- **Minimal fix:**
  - split `_run_check` into `_load_run` (config, base, files, detection),
    `_analyse` (cases-file or LLM path) and `_finish` (tests, report,
    exit code);
  - move request writing out of `_start_child`.
- **Regression test:** none new. The existing CLI tests cover the
  behavior.

## Per-request output cap (task 34 review question)

**Question:** `max_tokens` is checked before each request, but no output
limit is sent. Is that a real cost risk? Is a cap safe across
OpenAI-compatible servers?

**Evidence:**

- **Observed size.** In the 65 evaluation runs that made LLM calls (of
  76), the largest output for a single call was 2,990 tokens (`rerun-21a`,
  more-itertools-forward-842a2b1). The median run averaged about 1,250
  output tokens per call. The task 34 live run used 3,043 output
  tokens in 2 calls, 2,268 of them reasoning.
- **The risk is real but bounded.** Today a request is limited only by the
  model's own maximum output. Finding 4 shows that one function can use two
  full replies (four with the JSON-mode fallback) before the budget is asked
  again. A reasoning model that loops until its limit costs that limit twice.
  This is the one remaining unbounded part of an unpriced run.
- **Parameters by server** (official docs, checked 2026-11-11):
  - **OpenAI Chat Completions**
    (`developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create`):
    - `max_tokens` "is now deprecated in favor of `max_completion_tokens`,
      and is not compatible with o-series models";
    - `max_completion_tokens` is "an upper bound … including visible output
      tokens and reasoning tokens";
    - a reply that hits the limit has `finish_reason: "length"`.
  - **OpenAI reasoning guide** (`developers.openai.com/api/docs/guides/reasoning`):
    - a low limit can end "before any visible output tokens are produced",
      so you pay for reasoning with no answer;
    - OpenAI "recommends reserving at least 25,000 tokens for reasoning and
      outputs".
  - **Ollama** (`docs.ollama.com/api/openai-compatibility`): `max_tokens`
    is supported. `max_completion_tokens` is not listed.
  - **LM Studio** (`lmstudio.ai/docs/developer/openai-compat/chat-completions`):
    `max_tokens` is supported. `max_completion_tokens` is not listed.
  - **OpenRouter** (`openrouter.ai/docs/api-reference/parameters`): both are
    supported, and both cover reasoning tokens on most providers.
  - **Anthropic:** already sends `max_tokens: 16000` (`llm/anthropic.py:35`).

**Conclusion:** no single parameter is safe on every OpenAI-compatible
server. `max_tokens` is wrong for OpenAI reasoning models, and
`max_completion_tokens` is undocumented for Ollama and LM Studio. An unknown
parameter may be rejected (HTTP 400, so every function is skipped with
`llm request rejected`) or silently ignored.

**Recommendation: yes, in two steps.**

1. **Always (provider-independent, no risk).** Check the budget before the
   client's second attempt and before the JSON-mode fallback request (finding
   4). This removes the doubling. The overshoot is then at most one reply.
2. **Where the parameter is documented, send a cap** of 16,000 output tokens,
   the same as Anthropic: more than 5× the largest observed call.
   - `max_completion_tokens` for `openai` with the OpenAI URL and for the
     `openrouter` preset;
   - `max_tokens` for the `ollama` and `lmstudio` presets;
   - nothing for other `base_url` values.

   Lower the cap to the remaining `max_tokens` when that is smaller.

   If a server rejects the cap parameter (HTTP 400 naming it), drop it for
   that client, the same way the JSON-mode fallback works today.

   A cut-off reply then costs at most 16,000 output tokens and is reported
   as `invalid llm response`.

   Alternative: 25,000 (OpenAI's guidance for experimenting with reasoning
   models). It is safer against cutting off long reasoning, but gives a
   higher worst case. Measured replies are far below both values.

## Test coverage

Measured once at `ef71ad4`. The suite passed (935 tests) under coverage.

```text
uvx --with-requirements <uv export --all-groups> --with-editable . \
    coverage@7.10.7 run --branch --source=didibreak -m pytest -q
```

| Module | Lines | Line % | Branches | Branch % |
| --- | --- | --- | --- | --- |
| `__init__.py` | 1/1 | 100.0 | 0/0 | — |
| `__main__.py` | 0/2 | 0.0 | 0/0 | — |
| `_harness_child.py` | 101/156 | 64.7 | 33/44 | 75.0 |
| `cache.py` | 72/76 | 94.7 | 13/14 | 92.9 |
| `cases.py` | 136/138 | 98.6 | 36/38 | 94.7 |
| `cli.py` | 288/288 | 100.0 | 58/60 | 96.7 |
| `compare.py` | 96/98 | 98.0 | 38/40 | 95.0 |
| `config.py` | 185/187 | 98.9 | 67/70 | 95.7 |
| `contracts.py` | 114/123 | 92.7 | 62/70 | 88.6 |
| `functions.py` | 145/147 | 98.6 | 35/36 | 97.2 |
| `gitdiff.py` | 152/156 | 97.4 | 57/60 | 95.0 |
| `harness.py` | 134/138 | 97.1 | 19/24 | 79.2 |
| `intent.py` | 73/74 | 98.6 | 23/24 | 95.8 |
| `llm/__init__.py` | 39/39 | 100.0 | 14/14 | 100.0 |
| `llm/anthropic.py` | 64/67 | 95.5 | 15/18 | 83.3 |
| `llm/common.py` | 164/168 | 97.6 | 43/46 | 93.5 |
| `llm/openai_compat.py` | 86/86 | 100.0 | 18/18 | 100.0 |
| `llm/pricing.py` | 46/46 | 100.0 | 6/6 | 100.0 |
| `llm_session.py` | 129/135 | 95.6 | 25/26 | 96.2 |
| `pipeline.py` | 252/255 | 98.8 | 62/64 | 96.9 |
| `report/__init__.py` | 39/39 | 100.0 | 0/0 | — |
| `report/json.py` | 20/20 | 100.0 | 2/2 | 100.0 |
| `report/pytest_writer.py` | 176/179 | 98.3 | 47/50 | 94.0 |
| `report/text.py` | 76/76 | 100.0 | 36/36 | 100.0 |
| `testability.py` | 172/173 | 99.4 | 102/106 | 96.2 |
| **Total** | **2760/2867** | **96.3** | **811/866** | **93.6** |

`_harness_child.py` and `__main__.py` run in subprocesses that coverage
does not follow. Their low numbers are a measurement gap, not missing tests:
`test_harness*.py` and `test_cli.py::test_python_dash_m_prints_version`
run them. Subprocess coverage (`COVERAGE_PROCESS_START`) would measure them.

**The most important untested paths:**

1. **Labelling failures** (`llm_session.py:237-241`): `llm unavailable` and
   `request rejected` during intent labelling are never exercised. These
   failures leave all findings `unclear` with a reason that users see.
2. **Harness import crash** (`harness.py:266`, `:318`, `:367`):
   - a child that dies during import without writing a record
     (`import failed: process exited with code N`);
   - the same in `check_import`;
   - a skip reason from the second run of `run_cases`.
3. **Contract checks** (`contracts.py:47`, `:81-84`, `:97`, `:117`, `:122`,
   `:140`, `:152`): quoted annotations that do not parse, `typing.X`
   attribute names, a `dict[...]` annotation with one parameter, a tuple
   length mismatch, a source without a function. These decide whether
   findings are dropped.
4. **Anthropic** (`llm/anthropic.py:61`, `:173-174`): a reply without
   usage and a body that is not JSON. The client is not live-verified, so
   tests are its only check.
5. **Cache** (`cache.py:123-125`, `:130`): a failed atomic write that
   cleans up its temporary file, and a non-dict case item.
6. **`--cases-file` limits:** no test covers the values `nan` and `inf`
   (finding 2), or the cases-file validator's weaker rules (finding 11).

## Checks on main

From `python/` at `ef71ad4`:

- `uv run pytest -q`: 935 passed in 114.82s.
- `uv run ruff check .`: All checks passed!
- `uv run ruff format --check .`: 102 files already formatted.
- `uv run mypy src`: Success: no issues found in 25 source files.
- CI on main for `ef71ad4` (workflow `python`, push): success.
