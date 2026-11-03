# Safety

How your code is executed and isolated, and what is not covered.

## Which functions are never executed

Before running anything, didibreak skips functions it cannot run safely: async
functions, instance methods, generators, and functions with obvious I/O (files,
processes, network, databases). The full list of rules and I/O names is in
[limitations.md](limitations.md#functions-that-are-skipped).

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

The rest of this page (process isolation, timeouts, environment variables)
is written together with the execution harness.
