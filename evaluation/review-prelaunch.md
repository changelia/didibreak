# Independent review before launch

Review of `python/src/didibreak` at `3550550` (main, version 0.1.5 in the
code, not tagged), 2026-11-12. This is a report only: no product code was
changed. The owner chooses which findings are fixed before the launch.

**Reviewer note.** This review ran in a fresh session by a reviewer that
wrote none of this code. It is the fresh-session pass that the task 35
review left open for the task 34 code and the 35b and 35c changes.

## Scope and method

- Read in full: `testability.py`, `harness.py`, `_harness_child.py`,
  `arguments.py`, `gitdiff.py`, `config.py`, `pipeline.py`, `cli.py`,
  `llm/` (all five files), `llm_session.py`, `cases.py`, `cache.py`,
  `functions.py`, `intent.py`, `report/text.py`, `report/pytest_writer.py`,
  and the 35c diff (`git diff 1b2f42f 3550550 -- python/src`).
- Questions asked:
  - can a user function still receive LLM input and run commands, change
    files or reach the network;
  - can secrets reach user code or the output;
  - can the limits be bypassed;
  - did the 35c refactors change behavior.
- A finding is **CONFIRMED** only when it was reproduced at `3550550`, and
  the reproduction is in the finding. End-to-end reproductions are real
  `didibreak check` runs in throwaway git repositories with the hidden
  `--cases-file` option (no LLM), or against a fake provider on
  `127.0.0.1`. Every key and password shown is a made-up value.
- "Rule level" means a direct call of the function named in the finding.
- Output blocks show the real output, shortened to the lines that matter;
  JSON reports are condensed to the fields named. Temporary paths are
  written as `<tmp>`, `<repo>` and `<marks>`.
- Environment: macOS (Darwin 25.6.0), Python 3.12.3. No live LLM call was
  made.

What `docs/safety.md` and `docs/limitations.md` already state as a limit
(I/O in another module, I/O reached through `getattr`) is not reported as
a finding.

## Summary

| # | Category | Finding | Severity |
| --- | --- | --- | --- |
| 1 | CONFIRMED | Functions that run their argument as code (`eval`, `exec`, `pickle.loads`) are not skipped: a case string was executed as Python and ran a shell command | High |
| 2 | CONFIRMED | Same-module I/O is missed when it is reached through a class, a decorator or a renamed function. `os.system` and `subprocess.run` ran with a case argument in four variants. `safety.md` says same-module calls are followed | High |
| 3 | CONFIRMED | A `timeout` of 1e9 seconds or more hides every behavior change and exits 0 | Medium |
| 4 | CONFIRMED | `max_tokens` is not enforced when the server reports no `usage`: 10 requests sent with a limit that stops an honest server after 2 | Medium |
| 5 | CONFIRMED | Common credential names (`DB_PASS`, `*_PASSWD`, `*APIKEY`, `GH_PAT`, proxy URLs with a password) stay in the child environment. A kept value reached the text report, the generated test file and the labelling request | Medium |
| 6 | CONFIRMED | `--provider openai` or `--provider anthropic` keeps a `base_url` from `pyproject.toml`, so that provider's key is sent to the other host | Medium |
| 7 | CONFIRMED | The I/O table misses file changes without `open` (`Path.replace` overwrote a file chosen by the case) and several network and process modules | Medium |
| 8 | CONFIRMED (35c regression) | An absolute symbolic link that loops ends the run with a traceback and exit code 1; 0.1.4 handled the same repository | Low |
| 9 | CONFIRMED | Any unexpected exception leaves with a traceback and exit code 1, the code that means "findings" (non-ASCII key, `Retry-After: nan`, finding 8) | Low |
| 10 | CONFIRMED | A relative symbolic link with enough `../` still reaches the real repository from the copy; `safety.md` says relative links point into the copy | Low |
| 11 | CONFIRMED | The exit-2 error line and the 404 message print the provider's text to stderr without the control-character escaping of 35b | Low |
| 12 | CONFIRMED | An argument that contains a `#` comment passes the argument rule and breaks the whole generated test file (SyntaxError) | Low |
| 13 | CONFIRMED (mechanism) | Returned strings and bytes have no size limit: the parent used 232 MB for one 40 MB return value, about 5 bytes per character | Low |
| 14 | NOT REACHABLE TODAY | A key with a line break appears in the `LLMUnavailableError` text; nothing prints that text at present | Low |

Not broken, as far as this review could tell:

- LLM arguments are only ever read with `ast.literal_eval` (LLM replies,
  the cache, `--cases-file`, and again in the child);
- the API key is not passed to the child process, the request file, the
  cache or the reports;
- didibreak itself writes only inside `output_dir`.

Findings 1 and 2 are the ones to fix before the launch. They are the same
class as audit finding 1, which the owner treated as a safety issue: text
chosen by the LLM runs as code or as a shell command on the user's
machine.

## Findings

### 1. CONFIRMED: functions that run their argument as code are not skipped

- **Where:** `python/src/didibreak/testability.py:18-117` (`OBVIOUS_IO` has
  no entry for running code from data).
- **Trigger:** a changed function that passes an argument to `eval`, `exec`,
  `compile`, `__import__`, `importlib.import_module`, `runpy.run_path`,
  `pickle.loads`, `marshal.loads` or `ctypes`.
- **Reproduction** (rule level; `None` means "not skipped"):

  ```text
  eval                    -> None      exec                 -> None
  compile+exec            -> None      __import__           -> None
  importlib.import_module -> None      pickle.loads         -> None
  marshal.loads           -> None      runpy.run_path       -> None
  ctypes                  -> None      CONTROL os.system    -> obvious I/O: os.system
  ```

  **Reproduction** (end to end). `app/run.py` holds
  `def calc(expr): return eval(expr)`, changed to `eval(expr.strip())`. The
  second case is the string
  `"__import__('os').system('touch <marks>/ran_from_eval')"`, which is a
  valid literal:

  ```text
  $ didibreak check --cases-file cases.json --yes
  didibreak 0.1.5 · working tree vs HEAD (f5132627633f)
  1 changed function(s) to check (0 new)
  2 cases · 0 behavior changes · 0 flaky dropped
  exit 0
  marks: ['ran_from_eval']
  ```

  The same with `def load(blob): return pickle.loads(blob)` and the bytes
  literal `b"cos\nsystem\n(S'touch <marks>/ran_from_pickle'\ntR."`:

  ```text
  1 cases · 0 behavior changes · 0 flaky dropped
  exit 0
  marks: ['ran_from_pickle']
  ```

- **Impact:** `safety.md` says "LLM output is never executed as code". For
  a function that evaluates its input, the literal check does not give that:
  the string is data to didibreak and code to the function. A model asked
  for edge cases of an expression evaluator is likely to propose injection
  strings. The run above also shows no sign of it (exit 0, no findings).
- **Minimal fix:** add a group "runs code from data" to `OBVIOUS_IO`:
  - `calls`: `eval`, `exec`, `compile`, `__import__`,
    `importlib.import_module`, `runpy.*`, `pickle.load`, `pickle.loads`,
    `marshal.load`, `marshal.loads`, `yaml.load`, `yaml.unsafe_load`;
  - `modules`: `ctypes`, `code`, `dill`, `cloudpickle`.

  Update the list in `limitations.md`. The sentence in `safety.md` about
  `eval` describes I/O hidden behind `eval`; it should also say that a
  function that evaluates its argument is skipped.
- **Regression test:** one `skip_reason` case per new entry, and one
  `check --cases-file` test with the `eval` function above that asserts the
  marker file does not exist.

### 2. CONFIRMED: same-module I/O is missed through classes, decorators and renamed functions

- **Where:** `python/src/didibreak/testability.py:305-322`
  (`_called_functions` follows only calls whose name is a module-level
  function or `cls.x` / `self.x`) and `:293-302` (a bare name or attribute
  counts only for the `modules` entries, not for the `calls` entries).
- **Trigger:** the I/O is in the same module, but is reached by:
  - a class: `Runner(cmd).go()`, `Runner(cmd)` with I/O in `__init__`, or a
    module-level instance (`runner.go(cmd)`);
  - a decorator used without parentheses (`@audit`);
  - a renamed function: `run = os.system` inside the function, or
    `run = subprocess.run` / `sp = subprocess` at module level;
  - a function passed as a value (`map(helper, items)`), a helper defined
    under `if` or `try`, a module-level `lambda`, `functools.partial`,
    `from os import *`.
- **Reproduction** (rule level):

  ```text
  class instance helper           -> None   class __init__ helper     -> None
  module-level instance           -> None   bare decorator            -> None
  local alias f=os.system         -> None   module alias run=os.system -> None
  module alias sp=subprocess      -> None   module alias run=subprocess.run -> None
  callback map(helper)            -> None   helper under if           -> None
  lambda at module level          -> None   functools.partial         -> None
  from os import *                -> None
  CONTROL helper                  -> obvious I/O: os.system (via helper)
  ```

  **Reproduction** (end to end, four variants; each function builds
  `"touch <marks>/ran_" + name` and the case is `'X'`):

  ```text
  # class Runner: go() calls os.system(self.cmd);  def notify(name): return Runner(...).go()
  1 cases · 0 behavior changes · 0 flaky dropped      exit 0      marks: ['ran_X']
  # def notify(name): run = os.system; return run(...)
  1 cases · 0 behavior changes · 0 flaky dropped      exit 0      marks: ['ran_X']
  # @audit (wrapper calls os.system) on def greet(name)
  1 cases · 1 behavior changes · 0 flaky dropped      exit 1      marks: ['ran_x']
  # run = subprocess.run at module level; def notify(name): return run(..., shell=True)
  1 cases · 0 behavior changes · 0 flaky dropped      exit 0      marks: ['ran_X']
  ```

- **Impact:** the same as audit finding 1: a shell command built from an
  LLM-chosen string runs. `safety.md` states that the check covers "the
  module's imports and aliases" and "functions defined in the same module
  that the function calls, followed transitively", so a reader expects
  these cases to be skipped. Service classes and logging or audit
  decorators are common.
- **Minimal fix**, in order of value:
  1. In `_called_functions`, when a call names a module-level class
     (`Runner(...)`), follow every method of that class. When a call is
     `<anything>.method(...)` and exactly one module-level class defines
     `method`, follow it.
  2. Follow the decorators of the function under test, with or without
     parentheses.
  3. Treat a bare reference to a `calls` entry (`os.system` without a
     call) as I/O, as is already done for the `modules` entries.
  4. Record module-level assignments `name = <dotted name>` as aliases in
     `_import_aliases`, and collect functions defined under module-level
     `if` / `try`.
  5. Treat a same-module function passed as an argument as called.

  This stays a heuristic. `safety.md` should list what is still not
  followed.
- **Regression test:** the rule-level table above as a parametrized test,
  and the four end-to-end cases with "marker file not created".

### 3. CONFIRMED: a very large `timeout` hides every behavior change

- **Where:** `python/src/didibreak/config.py:118-125` (`_positive_number`
  has no upper bound) and `python/src/didibreak/_harness_child.py:234-237`
  (`signal.setitimer` is called outside the `try`).
- **Trigger:** `--timeout 1e9` or larger, or the same in `pyproject.toml`,
  for example to mean "no timeout". The value is finite, so the 35b check
  accepts it.
- **Reproduction:** `def double(x): return x * 2` changed to `x * 3`.

  ```text
  $ didibreak check --cases-file cases.json --yes
  1 cases · 1 behavior changes · 0 flaky dropped
    UNCLEAR      app/run.py::double(2)
                 before 4 → after 6
  exit 1
  $ didibreak check --cases-file cases.json --yes --timeout 1e19 --format json
  "findings": [], "functions_checked": 1, "cases_run": 1, "skipped": []
  exit 0
  $ python -c "import signal; signal.setitimer(signal.ITIMER_REAL, 1e9)"
  signal.itimer_error: [Errno 22] Invalid argument
  $ python -c "import signal; signal.setitimer(signal.ITIMER_REAL, 1e10)"
  OverflowError: timestamp out of range for platform time_t
  ```

  `1e8` is accepted by the timer; `1e9` and above are not (macOS, Python
  3.12; the limit on Linux was not measured). The child ends at the first
  case in both versions, both sides record `didibreak.ProcessExited`, the
  comparison sees no difference, and the function counts as checked.
- **Impact:** the same silent pass as audit finding 2 (`timeout = nan`),
  through a value that 35b still accepts. The exit-2 rule of 35b does not
  help, because `functions_checked` is 1.
- **Minimal fix:** give `timeout` an upper bound (for example 3,600
  seconds) in `_positive_number`, with the usual message. As a second
  line of defense, when both versions end with `ProcessExited` for every
  case of a function, report the function as skipped with an error reason
  instead of "checked".
- **Regression test:** `--timeout 1e9` exits 2 with the rule; a harness
  test where every case ends the process in both versions is not counted
  as checked.

### 4. CONFIRMED: `max_tokens` is not enforced when the server reports no usage

- **Where:** `python/src/didibreak/llm/openai_compat.py:42-58` and
  `llm/anthropic.py:45-56` (`parse_usage` returns zero tokens when `usage`
  is missing, and accepts negative numbers);
  `python/src/didibreak/pipeline.py:473-499` (`Budget.refusal` adds only
  reported tokens).
- **Trigger:** an OpenAI-compatible server or proxy whose replies have no
  `usage` object, or zeros in it.
- **Reproduction** (mock transport, ten functions, `max_tokens = 20,000`,
  every reply is 47,399 characters of valid cases):

  ```text
  usage field={'prompt_tokens': 600, 'completion_tokens': 8000}  requests sent=2  counted tokens=17200  skipped=['token limit']
  usage field=None                                               requests sent=10 counted tokens=0      skipped=[]
  usage field={'prompt_tokens': 0, 'completion_tokens': 0}       requests sent=10 counted tokens=0      skipped=[]
  usage field={'prompt_tokens': -100000, 'completion_tokens': 8000} requests sent=10 counted tokens=-920000 skipped=[]
  ```

- **Impact:** for a model without a price, `max_tokens` is the only limit
  (task 34). With such a server the limit only compares one request's
  estimate with the whole budget, so the run is bounded by
  `max_functions` × rounds, not by tokens. The report then also shows
  0 tokens. Not confirmed: whether a request that timed out and was
  retried by `post_with_retries` is billed by providers; those attempts
  are also counted as zero.
- **Minimal fix:** when a reply has no usable `usage`, count the request's
  estimate for the input and `len(reply text) / CHARS_PER_TOKEN` for the
  output, and say so once on stderr. Treat negative numbers as missing.
- **Regression test:** the second and fourth rows above as unit tests that
  expect two requests and the skip reason `token limit`.

### 5. CONFIRMED: common credential names stay in the child environment and can reach the output

- **Where:** `python/src/didibreak/harness.py:37-42` (`SECRET_SUFFIXES`,
  `SECRET_WORDS`, `URL_SUFFIXES`).
- **Trigger:** credentials in variables whose names the rule does not
  match.
- **Reproduction** (rule level, `child_environment`):

  ```text
  kept   : APIKEY, OPENAI_APIKEY, DB_PASS, SMTP_PASS, DB_PASSWD, GH_PAT, NPM_AUTH,
           HTTPS_PROXY (http://user:pw@proxy:8080),
           DATABASE_DSN (host=db user=app password=...), CONNECTION_STRING,
           AZURE_STORAGE_CONNECTION_STRING, DATABASE_URL (...?password=...),
           AWS_ACCESS_KEY_ID, SLACK_WEBHOOK_URL, PGPASSFILE
  removed: OPENAI_API_KEY, AWS_SECRET_ACCESS_KEY, GITHUB_TOKEN, PGPASSWORD, MYSQL_PWD,
           REDIS_URL (redis://:pw@host/0), PIP_INDEX_URL (https://user:pw@...),
           GOOGLE_APPLICATION_CREDENTIALS
  ```

  **Reproduction** (end to end, fake provider on `127.0.0.1`,
  `DB_PASS=FAKE-db-secret-123`). The function is
  `def dsn(db): return 'postgres://app:' + os.environ.get('DB_PASS', '') + '@db/' + db`,
  changed to use `db.lower()`:

  ```text
    UNCLEAR      app/run.py::dsn('Sales')
                 before 'postgres://app:FAKE-db-secret-123@db/Sales' → after 'postgres://app:FAKE-db-secret-123@db/sales'
  Reproducing tests: .didibreak/tests/test_dsn.py
  secret in the generated test file: True
  requests to the provider: 2 | secret in a request body: [False, True]
  ```

- **Impact:** a kept credential is readable by the code under test, and
  when it is part of a return value it is printed, written to
  `.didibreak/tests/` and sent to the LLM provider in the refinement and
  labelling requests. `safety.md` says that credentials "passed in other
  ways" are not detected, and `providers-and-costs.md` says that results
  are sent, but `_PASS`, `_PASSWD` and `APIKEY` are names a user would
  expect to be covered.
- **Minimal fix:** also remove names that end with `_PASS`, `_PASSWD`,
  `_PAT`, `_AUTH` or `APIKEY`, names that contain `CREDENTIAL`, and
  `*_PROXY` values that carry a password. For `*_DSN` and names that
  contain `CONNECTION_STRING`, remove values that contain `password=`,
  `pwd=` or `AccountKey=` (case-insensitive). Update the list in
  `safety.md`.
- **Regression test:** extend the `child_environment` test with these
  names, and with `HTTPS_PROXY=http://proxy:8080` (kept).

### 6. CONFIRMED: `--provider openai` keeps the file's `base_url`, so the key goes to another host

- **Where:** `python/src/didibreak/config.py:339-346` (`_below_preset`
  drops the file's `base_url` and `api_key_env` only when the flag names a
  preset).
- **Trigger:** `pyproject.toml` configures one server with a `base_url`,
  and the user switches provider on the command line to `openai` or
  `anthropic`.
- **Reproduction** (`client_settings(build_config(file, cli), env)`):

  ```text
  file: provider=ollama base_url=http://gpu-box:11434/v1 | cli: --provider openai --model gpt-6-luna
      -> url=http://gpu-box:11434/v1 key=<OPENAI_API_KEY> cap=None
  file: provider=openai base_url=https://proxy.example/v1 | cli: --provider anthropic --model claude-haiku-5-5
      -> url=https://proxy.example/v1 key=<ANTHROPIC_API_KEY> cap=None
  CONTROL file: provider=openrouter base_url=https://openrouter.ai/api/v1 | cli: --provider ollama --model l
      -> url=http://localhost:11434/v1 key=None cap=max_tokens
  ```

- **Impact:** the mirror case of the task 34 review change ("`--provider
  ollama` must not use a pyproject OpenRouter URL"). The OpenAI or
  Anthropic key is sent in a header to the host from the file, in the
  first row over plain HTTP. The output cap is also off, because the host
  is not the provider's own.
- **Minimal fix:** apply the same rule to every provider: a `--provider`
  flag that differs from the file's `provider` drops the file's `base_url`
  and `api_key_env`; values given as flags still win.
- **Regression test:** the first two rows, expecting the provider's
  default URL.

### 7. CONFIRMED: file changes without `open`, and several modules, are not in the table

- **Where:** `python/src/didibreak/testability.py:18-117`.
- **Trigger:** a changed function that uses one of these (rule level, all
  `None`): `Path.replace`, `os.write`, `os.chdir`, `os.utime`, `os.mkfifo`,
  `os.putenv`, `tempfile.mkdtemp`, `logging.FileHandler`,
  `zipfile.ZipFile(...).extractall`, `multiprocessing.Process`,
  `xmlrpc.client`, `asyncio.open_connection`, `socketserver`, `nntplib`,
  `webbrowser.open_new` (`webbrowser.open` is caught by the `open` method
  rule).
- **Reproduction** (end to end).
  `def archive(name): Path('<marks>/report.txt').replace('<marks>/' + name)`,
  with `report.txt` and `other.txt` present and the case `'other.txt'`:

  ```text
  1 cases · 0 behavior changes · 1 flaky dropped
  exit 0
  marks: ['other.txt']
  other.txt now holds: important        # the content of report.txt
  ```

  `other.txt` was overwritten and `report.txt` is gone.
- **Impact:** files named by an LLM-chosen string are moved over other
  files. `limitations.md` says the list is not complete and names
  `Path.replace` as left out on purpose, so this is a known gap with a
  real effect, not a new class.
- **Minimal fix:**
  - match `replace` as a path method only when the call has exactly one
    positional argument and no keywords (`str.replace` needs two);
  - add `calls`: `os.write`, `os.chdir`, `os.utime`, `os.mkfifo`,
    `os.mknod`, `os.putenv`, `tempfile.*`, `logging.FileHandler`;
  - add `modules`: `multiprocessing`, `xmlrpc.client`, `socketserver`,
    `telnetlib`, `nntplib`, `webbrowser`, `zipfile`, `tarfile`;
  - add `asyncio.open_connection` and `asyncio.start_server` to `calls`.
- **Regression test:** one `skip_reason` case per entry, plus
  `'a'.replace('b', 'c')` staying testable.

### 8. CONFIRMED (35c regression): a looping absolute symbolic link ends the run with a traceback

- **Where:** `python/src/didibreak/gitdiff.py:388-405` (`points_into`,
  added in `bc322ab`): `Path.resolve()` raises `RuntimeError` for a link
  loop on Python 3.12 (run here; 3.11 has the same standard-library code
  and was not run).
- **Trigger:** the repository contains an absolute symbolic link that
  points to itself or forms a loop (for example a broken link left by a
  tool).
- **Reproduction** (a repository with `loop -> <repo>/loop` and one changed
  function):

  ```text
  $ didibreak check --cases-file cases.json --yes          # 3550550
    File ".../pathlib.py", line 1237, in check_eloop
      raise RuntimeError("Symlink loop from %r" % e.filename)
  RuntimeError: Symlink loop from '<tmp>/loop-yf3qzrt8/loop'
  exit 1
  $ python -m didibreak check --cases-file cases.json --yes   # source of 1b2f42f (0.1.4)
  1 cases · 1 behavior changes · 0 flaky dropped
    UNCLEAR      app/run.py::double(2)
  exit 1
  ```

- **Impact:** a run that worked in 0.1.4 now stops with a traceback. Rare,
  but it is the only behavior change found in the 35c refactors (see
  "35c refactors" below).
- **Minimal fix:** in `points_into`, catch `RuntimeError` and `OSError`
  from `resolve()` and treat the link as pointing into the repository
  (leave it out).
- **Regression test:** a fixture repository with such a link; the copy is
  made and the link is not in it.

### 9. CONFIRMED: an unexpected exception exits with code 1, which means "findings"

- **Where:** `python/src/didibreak/cli.py:875-894` (`main` catches only
  `KeyboardInterrupt`) and `:843` (the `check` path catches a fixed list of
  error types).
- **Trigger:** any exception outside that list. Three were reproduced:
  - an API key with a non-ASCII character;
  - a provider that answers 429 with `Retry-After: nan`
    (`llm/common.py:297-301`; rule level: `_backoff_seconds` returns `nan`
    and `time.sleep(nan)` raises `ValueError`);
  - finding 8.
- **Reproduction** (real CLI, fake provider on `127.0.0.1`, the key is a
  fake value with `é` appended):

  ```text
  $ didibreak check --provider openai --model m --base-url http://127.0.0.1:<port>/v1 --yes --format json
    File ".../httpx/_models.py", line 82, in _normalize_header_value
      return value.encode(encoding or "ascii")
  UnicodeEncodeError: 'ascii' codec can't encode character '\xe9' in position 40: ordinal not in range(128)
  exit 1
  ```

  The traceback did not contain the key.
- **Impact:** exit code 1 is documented as "failing findings", and the
  agent snippet tells agents to fix the code on findings. With
  `--format json` stdout is empty, so an agent sees exit 1 and no report.
- **Minimal fix:** in `main`, catch `Exception` around `_run_check`, print
  `didibreak: error: unexpected <Type>: <message>` and a request to report
  it, and return 2. Reject a key that is not printable ASCII in
  `read_api_key` with a clear message (see also finding 14). Make
  `_backoff_seconds` ignore a value that is not finite.
- **Regression test:** a patched step that raises `RuntimeError` gives exit
  2 and one line on stderr; `Retry-After: nan` falls back to the
  exponential backoff.

### 10. CONFIRMED: a relative symbolic link can still reach the real repository

- **Where:** `python/src/didibreak/gitdiff.py:402-404` (`points_into`
  returns False for every relative link).
- **Trigger:** a relative link with enough `../` to reach the file-system
  root, followed by the repository's absolute path. It resolves to the
  same place from the temporary copy.
- **Reproduction** (`working_tree_copy` on a repository with such links):

  ```text
  points_into(abs_link.txt) = True
  points_into(rel_link.txt) = False        # ../../(40 times)/<repo>/data/real.txt
  points_into(rel_dir) = False             # ../../(40 times)/<repo>/data
  in copy: ['data', 'rel_dir', 'rel_link.txt']
  # write through both links inside the copy, then:
  repo data/real.txt now: written through the copy | data/: ['new_file.txt', 'real.txt']
  ```

- **Impact:** low; such links are unusual. But `safety.md` says "Relative
  links point into the copy and are kept", which is not true for them.
- **Minimal fix:** decide by where the link would resolve from its place
  in the copy: skip any link, absolute or relative, whose target resolved
  from the copy's location is inside the real repository. Or correct the
  sentence in `safety.md`.
- **Regression test:** the fixture above; neither relative link is in the
  copy.

### 11. CONFIRMED: provider text reaches the terminal unescaped on stderr

- **Where:** `python/src/didibreak/cli.py:816-818` (the exit-2 line built by
  `nothing_checked_error`) and `:843-844` (`LLMModelError`, which quotes
  the provider's 404 text). `report/text.py` escapes the same skip reason
  in the report itself.
- **Trigger:** a provider error message that contains control characters.
- **Reproduction** (fake provider answering 400 with
  `bad \x1b[2J\x1b]0;pwned\x07 request`; output shown with `cat -v`):

  ```text
  didibreak: error: no changed function could be checked: app/run.py::double (llm request rejected: HTTP 400: bad ^[[2J^[]0;pwned^G request). Fix the cause (provider, limits or imports) and run again
  ```

- **Impact:** low, the same as audit finding 8: the terminal can be cleared
  or its title changed. The provider is the server the user chose, but
  services such as OpenRouter pass upstream messages on.
- **Minimal fix:** pass every `didibreak: error:` and `warning:` line that
  can contain provider text through `printable()`. Move `printable` to a
  module both `cli.py` and `report/text.py` can import.
- **Regression test:** the reproduction; stderr contains no ESC character.

### 12. CONFIRMED: a comment inside an argument breaks the generated test file

- **Where:** `python/src/didibreak/arguments.py:21-39` (`literal_problem`
  accepts any text `ast.literal_eval` accepts) and `:75-78` (`format_call`
  joins the texts as they are); used by
  `python/src/didibreak/report/pytest_writer.py:111-121`.
- **Trigger:** an argument such as `2  # the smallest even prime`.
  `ast.literal_eval` ignores the comment, so the case is valid.
- **Reproduction** (two cases, the first one with the comment):

  ```text
    UNCLEAR      app/run.py::double(2  # the smallest even prime, 1)
                 before 5 → after 7
  Reproducing tests: .didibreak/tests/test_double.py
  # .didibreak/tests/test_double.py:
      result = double(2  # the smallest even prime, 1)
  $ pytest -q .didibreak/tests/test_double.py
  E   SyntaxError: '(' was never closed
  ERROR .didibreak/tests/test_double.py
  1 error in 0.10s
  ```

- **Impact:** the file does not load, so the test of the second, valid
  finding is lost too. The comment cannot add code: the rest of the line
  is swallowed, which always ends in a syntax error. This behavior is the
  same before and after 35c.
- **Minimal fix:** store arguments in a normal form:
  `ast.unparse(ast.parse(text, mode="eval"))` in `case_problem`'s callers
  when a case is accepted. Comments and odd spacing are then gone
  everywhere (reports, tests, cache, finding ids).
- **Regression test:** the reproduction; the written file compiles, and
  the report shows `double(2, 1)`.

### 13. CONFIRMED (mechanism): returned strings and bytes have no size limit

- **Where:** `python/src/didibreak/_harness_child.py:80-82` (`_scalar`
  stores the whole string or the hex of the bytes; `_MAX_NODES` counts
  values, not characters) and `python/src/didibreak/harness.py:196-203`
  (the parent reads the whole results file).
- **Trigger:** a function whose return value grows with a number argument,
  for example `text.ljust(width)` or `"x" * n`, with a large case value.
- **Reproduction** (`def pad(text, width): return text.ljust(width)`, peak
  memory of the didibreak process from `/usr/bin/time -l`):

  ```text
  width=      1,000  parent peak RSS=31 MB
  width= 20,000,000  parent peak RSS=131 MB
  width= 40,000,000  parent peak RSS=232 MB
  ```

  About 5 bytes per returned character in the parent, on top of the child.
  Larger values were not run on purpose: `1000000000` is a valid literal
  and would need about 5 GB.
- **Impact:** a large number is a typical edge case for an LLM to propose.
  The per-case timeout bounds time, not memory, and the child has no
  memory limit.
- **Minimal fix:** in `_scalar`, raise `_Unrepresentable` for a `str` or
  `bytes` longer than a fixed size (for example 100,000). The value is
  then compared by type only, like other values that are too large.
  Optionally set `RLIMIT_AS` in the child.
- **Regression test:** a harness test with a 1,000,000-character return
  value: the outcome has no `value` and the results file stays small.

### 14. NOT REACHABLE TODAY: a key with a line break is in the unavailable-error text

- **Where:** `python/src/didibreak/llm/common.py:341` and `:352`. The
  transport error quotes the header as Python bytes
  (`b'Bearer ...\n'`), so `redact()` (`:194`), which looks for the exact
  key text, finds nothing.
- **Trigger:** an API key variable whose value ends with, or contains, a
  line break.
- **Reproduction** (client level, real local HTTP server, fake key):

  ```text
  LLMUnavailableError: the LLM provider is unavailable after 3 attempts
  (LocalProtocolError: Illegal header value b'Bearer sk-FAKE-not-a-real-key-0123456789\n')
  ```

  End to end, the key did **not** appear: `pipeline._ask` and
  `LLMSession.label` drop the message and report only `llm unavailable`
  (checked with `-v`, text and JSON).
- **Impact:** no leak today. The module docstring of `llm/common.py`
  promises that every error message is free of the key, and that is not
  true for this one, so a later change that prints the message (for
  example to explain why the provider is unavailable) would leak it. A
  second effect is real today: a key with a trailing line break gives
  `llm unavailable` after three attempts, which points the user at the
  provider instead of the key.
- **Minimal fix:** in `read_api_key`, reject a key with whitespace, control
  or non-ASCII characters before any request ("`<VARIABLE>` must hold only
  the key"). In `post_with_retries`, do not retry
  `httpx.LocalProtocolError`, and never put the transport error's text in
  the message for it.
- **Regression test:** a key with `\n` exits 2 with the variable's name and
  without any part of the key.

## 35c refactors

The 35c diff was read line by line against `1b2f42f`.

- `cli.py`: the split of `_run_check` into `_prepare`, `_print_header`,
  `_report_nothing_to_check`, `_analyse_cases_file`, `_analyse_with_llm`
  and `_finish`, and of `_build_report` into `_skipped_items` and
  `_report_usage`, keeps the same order of steps, the same caught error
  types and the same exit codes. `detect_changed_functions` moved inside
  the first `try`; it raises none of the caught types, so nothing changes.
- `harness.py`: `_write_request`, `_spawn` and `_wait_or_kill` do what
  `_start_child` did, including killing the process group in every case.
- `gitdiff.py`: `_changes_since` and `_as_python_change` give the same
  three outcomes per changed file as the old `if` chain. The new
  `points_into` is the one regression (finding 8).
- `arguments.py`: `case_problem` is used by LLM replies, the cache,
  `--cases-file` and the harness. The only behavior changes are the two
  recorded in the Decision log (long arguments and keyword names for
  `--cases-file` and the cache). Finding 12 is older than 35c.

## Checked, no finding

Items without a stated run were checked by reading the code.

- **Windows check** (task 34). With `sys.platform` patched to `win32`:
  `check` and `init-agents` return 2 with the one-line message; a bare
  `didibreak`, `--version` and `check --help` work.
- **Preset precedence** (task 34), apart from finding 6: `--provider
  ollama` over a `pyproject.toml` OpenRouter URL and key variable gives
  `http://localhost:11434/v1` and no key.
- **nan / inf** (35b): `timeout`, `max_cost`, `temperature` and `prices`
  reject them; `max_tokens`, `cases`, `max_functions` and `refine_rounds`
  are integers with bounds.
- **Budget re-checks and the reply cap** (35b): with a server that
  reports usage, the retry and the JSON-mode fallback ask the budget
  first, and the cap field follows the documented table. The audit's
  suggestion to drop the cap when a server rejects it is not implemented;
  the Decision log does not require it.
- **Exit 2 when nothing could be checked** (35b): behaves as decided. Two
  cases outside the decision still exit 0: finding 3, and a run in which
  one function was checked while the others failed.
- **A model without a price on `localhost`** is shown as `cost $0 (local)`
  with no warning, also when the local port is a proxy to a paid API.
  This follows the owner decision of 2026-11-07 and is documented;
  `max_tokens` still applies. Worth one sentence in
  `providers-and-costs.md`.
- **Cache and `--cases-file`**: both validate every case again on load; an
  edited cache file can only cause a new LLM request.

## Checks on main

From `python/` at `3550550`:

- `uv run pytest -q`: 1055 passed in 136.32s (exit 0).
- `uv run ruff check .`: All checks passed! (exit 0).
- `uv run ruff format --check .`: 107 files already formatted (exit 0).
- `uv run mypy src`: Success: no issues found in 26 source files (exit 0).

## Limits of this review

- No live LLM call: the provider behavior (cap fields, usage, billing of
  timed-out requests) was checked against mock and local fake servers
  only.
- Run on macOS with Python 3.12 only. The timer limit in finding 3 and the
  `RuntimeError` in finding 8 depend on the platform and the Python
  version (3.13 changed `Path.resolve()` for loops); neither was measured
  elsewhere.
- `compare.py`, `contracts.py`, `report/json.py` and the prompt files were
  read only where the reviewed paths use them.
- Coverage was not measured again.
