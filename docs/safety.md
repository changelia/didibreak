# Safety

How your code is executed and isolated, and what is not covered.

> For code you did not write (external pull requests, unattended agents),
> run didibreak inside a container or a CI job.

## Which functions are never executed

Before running anything, didibreak skips functions it cannot run safely: async
functions, instance methods, generators, and functions with obvious I/O (files,
processes, network, databases). The full list of rules and I/O names is in
[limitations.md](limitations.md#functions-that-are-skipped). These rules read
the source; they are a fast first filter. What they miss is run under the
[runtime I/O guard](#the-runtime-io-guard).

A function is skipped when a rule matches in **either** the base or the
current version, because both versions are executed. The reason then ends with
`(base version)`, for example `obvious I/O: os.remove (base version)`.

The I/O check looks at:

- the function's own body, including helpers defined inside it;
- the module's imports and aliases (`from subprocess import run`,
  `import shutil as sh`);
- functions defined in the **same module** that the function calls, followed
  transitively (`clean()` → `_remove()` → `shutil.rmtree()`).

## The runtime I/O guard

The skip rules cannot see I/O behind a class, a decorator, a renamed
function, `eval`, `exec`, `pickle.loads` or a helper in another module. So
every process that runs your code also has a runtime guard: an audit hook
([PEP 578](https://peps.python.org/pep-0578/)) installed before your module
is imported. While your module is imported and while a case runs, it stops:

- running commands and starting or signalling processes (`os.system`,
  `subprocess`, `os.exec*`, `os.spawn*`, `os.posix_spawn`, `os.fork`,
  `os.kill`);
- network access: connecting, binding, sending to an address and looking
  up names, whichever Python library does it;
- loading native code with `ctypes`, and SQLite extensions;
- writing, creating, deleting, renaming or changing the permissions of
  files and folders outside the process's own temporary folder. That folder
  is the process's working directory and `TMPDIR`, so relative paths and
  the `tempfile` module still work; it is removed afterwards. An SQLite
  database in memory (`:memory:`) is allowed.

Reading files is allowed. The full list of audit events is
`BLOCKED_EVENTS` in
[`_io_guard.py`](../python/src/didibreak/_io_guard.py).

When the guard stops something, the function is skipped with the reason
`blocked: <event>`, for example `blocked: os.system`, or `blocked: open`
for a file written outside the temporary folder. `(base version)` is
added when it happened in the base version. A blocked function is never
reported as a finding and gets no reproducing test. The guard raises an
exception that `except Exception` does not catch, and it records the first
blocked event even if your code catches that exception. Python has no way
to remove an audit hook, so your code cannot switch it off.

A module that writes a file outside the temporary folder while it is
imported (a cache or a log file, for example) is stopped too: its functions
are skipped with `blocked: open`.

## What is not covered

**The guard is defence in depth, not a sandbox.** It sees only operations
for which Python raises an audit event:

- **C extensions** that do their own I/O raise no event and are not
  stopped. A database driver built on a C library (for example `psycopg2`,
  which connects through libpq) can still reach the network.
- A few standard calls raise no event: `os.mkfifo`, `os.mknod`,
  `os.setxattr` and the private `_posixsubprocess.fork_exec`.
- Code that sets out to defeat the guard from inside the same process (for
  example by changing the hook's own data) can do so. The guard is meant
  for ordinary code given unusual inputs, not for hostile code.
- Effects that are not I/O still happen: memory and CPU use (the per-case
  timeout still applies), and changes to the process itself.
- Importing your module runs its top-level code, under the guard.

A container (or a CI job) is the real isolation. There is none in 0.1.x:
for code you did not write, run didibreak inside a container or a CI job
yourself.

## What didibreak writes

didibreak writes only inside its output folder (`output_dir`, default
`.didibreak/` at the repository root): the case cache and the reproducing
tests (`.didibreak/tests/`). The folder ignores itself with its own
`.gitignore` containing `*`, so it never shows up in `git status`. Your own
`.gitignore` and your code are never edited.

## What the LLM can and cannot do

The LLM only proposes input values. Every argument it returns must pass
`ast.literal_eval`, so it can contain only literals such as numbers,
strings, lists and dicts; anything else is dropped before any code runs.
didibreak never executes LLM output as code. A function of yours that runs
its own input as code (`eval`, `exec`, `pickle.loads`) can still turn such
a string into code; the [runtime I/O guard](#the-runtime-io-guard) then
stops what that code can do to your machine (commands, network, file
changes), but not the evaluation itself.

## How a function is run

- **Your working tree is never executed.** The base version runs from a
  temporary git worktree of the base commit. The current version runs from a
  temporary copy of your working tree that holds the files git sees: tracked
  and untracked files, without ignored files, `.git` and the output folder.
  Symbolic links are copied as links, except absolute links that point
  into your repository (`data -> /home/me/project/data`): through them,
  code run from the copy would read and write your real files, so they
  are left out. Relative links point into the copy and are kept. Absolute
  links outside the repository are kept; writes through them are stopped
  by the runtime I/O guard, like any write outside the process's
  temporary folder. Both trees are removed afterwards, also after an
  error or Ctrl-C.
- **Separate processes.** Each version of a function runs in a new Python
  process started with the `--python` interpreter. Every case runs twice per
  version, in two separate processes, so one function takes four processes
  per round.
- **Only the version under test is imported.** The version's import root is
  put first on `sys.path`. `PYTHONPATH`, the other `PYTHON*` variables and
  the user site-packages folder are ignored. If the module is still found
  outside that version's folder, for example in an installed or editable copy
  of your package, the function is skipped with `import resolved outside
  tree`.
- **Nothing is written into your project by the run itself.** No
  `__pycache__` files are written, the working directory is a new temporary
  folder, and your function's printed output is discarded.
- **Timeouts.** Each case stops after `timeout` seconds (default 10) and is
  recorded as a timeout; the other cases still run. Code that catches every
  exception (`except BaseException`) cannot stop this for long: the process
  and any processes it started are killed after a total of `timeout` ×
  number of cases plus 5 seconds.
- **Crashes.** A case that ends the process (`os._exit`, a crash in a C
  extension) is recorded as the exception `didibreak.ProcessExited`, and the
  remaining cases run in a new process.
- **Repeatable results.** `PYTHONHASHSEED=0`, `TZ=UTC`, and `random.seed(0)`
  before every case. A case whose two runs still differ is dropped as flaky.
- **Data crosses process boundaries as JSON only**, never `pickle`.

### Environment variables that are removed

Before your code runs, didibreak removes variables that look like
credentials, so the function under test cannot use your API keys, tokens or
database passwords. Names are matched ignoring case. A variable is removed
when its name:

- ends with `_KEY`, `_PWD`, `_PAT` or `_CREDENTIALS` (`OPENAI_API_KEY`,
  `AWS_SECRET_ACCESS_KEY`, `MYSQL_PWD`, `GH_PAT`,
  `GOOGLE_APPLICATION_CREDENTIALS`);
- contains `PASS`, `TOKEN`, `SECRET`, `APIKEY` or `API_KEY` (`DB_PASS`,
  `SMTP_PASSWD`, `PGPASSWORD`, `GITHUB_TOKEN`, `OPENAI_APIKEY`). `PASS`
  also matches names that only contain those letters, such as `BYPASS_X`;
  they are removed too;
- is the variable named by `api_key_env`;
- ends with `_URL`, `_URI`, `_DSN` or `_PROXY` **and** its value is a URL
  with a password (`postgres://app:s3cret@db/prod`,
  `redis://:s3cret@cache:6379`, `HTTPS_PROXY=http://me:s3cret@proxy:8080`;
  lower-case names such as `https_proxy` too).

A connection string without a password stays, because the code under test
may need it: `DATABASE_URL=postgres://localhost/app` and
`postgres://app@localhost/app` are kept, and so is a proxy without a
password. So are `PWD` and `OLDPWD`, which
hold folders, not passwords. Credentials passed in other ways (a URL in a
variable with another name, a config file) are not detected.

Code that reads such a variable sees it as missing, which can change its
behavior.

### When a function cannot be run

Before the first LLM request, every function's module is imported once in
both versions (nothing is called), so a function that cannot be imported is
skipped with one of these reasons without costing tokens. Runs with
`--cases-file` send no requests and skip this step.

| Reason | When |
| --- | --- |
| `import failed: <ExceptionType>` | Importing the module raised an exception. |
| `import failed: process exited with code <N>` | The process ended while importing the module. |
| `import timed out` | Importing the module took longer than the time for all cases. |
| `import resolved outside tree` | The module was found outside the version being tested. |
| `function not found after import` | The module has no such function or method. |
| `blocked: <event>` | Importing the module tried an operation the [runtime I/O guard](#the-runtime-io-guard) stops. |
