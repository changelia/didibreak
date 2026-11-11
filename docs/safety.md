# Safety

How your code is executed and isolated, and what is not covered.

> For code you did not write (external pull requests, unattended agents),
> run didibreak inside a container or a CI job.

## Which functions are never executed

Before running anything, didibreak skips functions it cannot run safely: async
functions, instance methods, generators, and functions with obvious I/O (files,
processes, network, databases). The full list of rules and I/O names is in
[limitations.md](limitations.md#functions-that-are-skipped).

A function is skipped when a rule matches in **either** the base or the
current version, because both versions are executed. The reason then ends with
`(base version)`, for example `obvious I/O: os.remove (base version)`.

The I/O check looks at:

- the function's own body, including helpers defined inside it;
- the module's imports and aliases (`from subprocess import run`,
  `import shutil as sh`);
- functions defined in the **same module** that the function calls, followed
  transitively (`clean()` → `_remove()` → `shutil.rmtree()`).

## What is not covered

- **Calls into other modules are not followed.** If `store()` calls
  `helpers.save()` and `save()` writes a file, `store()` is not skipped and the
  write happens when didibreak runs it. Keep side effects out of the functions
  you change, or exclude those files with `exclude`.
- I/O that is not on the list, or that happens through dynamic code
  (`getattr`, `eval`, plugins), is not detected.
- Importing your module runs its top-level code.
- Your function's own side effects still happen: a file written to an
  absolute path, for example, is really written. There is no container or
  sandbox in 0.1.x: for code you did not write, run didibreak inside a
  container or a CI job yourself.

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
LLM output is never executed as code.

## How a function is run

- **Your working tree is never executed.** The base version runs from a
  temporary git worktree of the base commit. The current version runs from a
  temporary copy of your working tree that holds the files git sees: tracked
  and untracked files, without ignored files, `.git` and the output folder.
  Both are removed afterwards, also after an error or Ctrl-C.
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
credentials, so the function under test cannot use your API keys or tokens.
A name matches, ignoring case, when it:

- ends with `_KEY` (`OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`);
- contains `TOKEN`, `SECRET` or `PASSWORD` (`GITHUB_TOKEN`, `DB_PASSWORD`);
- is the variable named by `api_key_env`.

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
