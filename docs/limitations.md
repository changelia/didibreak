# Limitations

What didibreak cannot check, shared and per language.

## Git

- **Base version:** the working tree (committed, staged, unstaged and
  untracked files) is compared with one base commit (`--base`, default
  `HEAD`). A repository without any commit has no base and is an error.
- **Submodules:** changes inside git submodules are not checked; git reports
  a changed submodule only as its folder.
- **Shallow clones:** a base older than the cloned history cannot be found;
  fetch more history first (`git fetch --unshallow`).
- **Renames:** a rename is recognised when git can see it, for example after
  `git mv` or a commit. A file that was moved but not yet added to git is
  treated as a deleted file plus a new file.
- **Deleted files:** functions in deleted files are not checked.

## Which functions are compared

- Candidates are module-level functions and the methods of module-level
  classes. A function nested inside another function is not compared on its
  own; a change inside it shows up as a change of the enclosing function.
  Methods of nested classes are not compared at all.
- A function counts as changed only when its code changes. Formatting,
  comments and docstrings are ignored.
- A file that cannot be parsed in either version (syntax error, unknown
  encoding) is skipped and reported with the reason.
- At most `max_functions` functions are checked per run (default 10), in
  order of file path, then line; the rest are reported as not checked.

## Functions that are skipped

v0.1 does not run these functions; the report lists each one with its reason.
A rule that matches in either the base or the current version skips the
function; see [safety.md](safety.md).

| Reason | When |
| --- | --- |
| `async function` | The function is defined with `async def`. |
| `instance method` | A method without `@staticmethod` or `@classmethod`; it needs an instance. |
| `generator` | The function itself contains `yield` or `yield from`. |
| `obvious I/O: <name>` | The body (including helpers defined inside it) uses one of the I/O names below. |

Obvious I/O. Names are resolved through the module's imports and aliases, so
`from subprocess import run` and `import shutil as sh` are recognized:

- calls to `open`, `os.remove`, `os.unlink`, `os.rmdir`, `shutil.rmtree`,
  `shutil.move`, `shutil.copy*` (any `shutil` function starting with `copy`),
  `urllib.request.*` (any function in `urllib.request`) and `sqlite3.connect`;
- any use or import of the modules `subprocess`, `requests`, `httpx`, `socket`;
- `pathlib.Path` methods `open`, `read_bytes`, `read_text`, `write_bytes`,
  `write_text`, `unlink`, `rmdir`, `mkdir`, `touch`, matched by method name on
  any object, because the type of a variable is not known from the source;
- database calls `<receiver>.<method>(...)` where the receiver is `session`,
  `db`, `cursor`, `conn` or `connection` and the method is `add`, `commit`,
  `delete`, `execute`, `executemany`, `flush`, `merge`, `query`, `refresh`,
  `rollback` or `scalars` (for example `session.commit()`).

The check is a scan of names in the source, so it can miss I/O that is not
on this list, and it can skip a function that only looks like I/O. Rules are
checked in the order of the table; the first match is the reason.

## Inputs from the LLM

- Arguments are Python literals only. Functions that need objects (class
  instances, dates, file handles) as arguments get no useful cases and are
  reported as `no valid cases` or show only type errors.
- The LLM also proposes inputs of types a function does not accept (bytes or
  lists for a string parameter, floats for a count). When only such an
  input behaves differently, the finding is real but rarely matters; for new
  functions most `new_function` findings are of this kind (see
  `evaluation/README.md`).
- The LLM picks the inputs, so a change on a path no proposed input reaches
  is not found. Each run may propose different inputs; cached cases are
  reused while the function does not change.
- The cost estimate is an estimate: a retry after an unusable reply is not
  included, and the real token counts can differ.

## Running functions

- Linux and macOS only: per-case timeouts use Unix signals.
- Files ignored by git (for example `.env` or generated data) are not in the
  temporary copy the current version runs from, nor in the base version.
  Code that needs them when it is imported or called fails or behaves
  differently. A common case: packages that import a version file their
  build backend generates (such as `_version.py` from hatch-vcs or
  setuptools-scm) fail with `import failed: ModuleNotFoundError`, and
  packages that read their own version with `importlib.metadata` fail with
  `import failed: PackageNotFoundError` unless they are installed in the
  `--python` environment.
- The working tree is copied for every run. Measured: under 0.1 s for
  libraries of up to about 150 files, 2.1 s for a 7,000-file repository
  (Django, macOS, 2026-11-09).
- The `--python` interpreter must be Python 3.11 or newer.
- Return values are compared by value for `None`, `bool`, `int`, `float`,
  `str`, `bytes`, and lists, tuples, sets, frozensets and dicts of these.
  Subclasses of these types (`namedtuple`, `OrderedDict`, `defaultdict`,
  `IntEnum`, `StrEnum`, ...) are compared through their builtin base, and
  their class must match too: `Point(1, 2)` and `(1, 2)` differ. The order of
  an `OrderedDict` and the `default_factory` of a `defaultdict` are not
  compared.
- Other `Enum` members are compared by their class and member name.
- Anything else, including dataclasses and other objects, and values with
  more than 10,000 elements or nested more than 100 levels deep, is compared
  by type only.
- Environment variables that look like credentials are removed before your
  code runs; see [safety.md](safety.md#environment-variables-that-are-removed).

## Reproducing tests

- New functions, and cases where the base version timed out or ended the
  process, get no test.
- Values that are not Python literals (objects, dataclasses, `nan`,
  truncated long values) are checked by their type only, so such a test can
  pass on the change even though didibreak reported a difference.
- The tests set `TZ=UTC` and seed `random` like the harness, but
  `PYTHONHASHSEED` is not reproduced (it must be set before Python starts)
  and credential variables are not removed. Code whose result depends on
  the hash seed, such as the iteration order of a set of strings, or on
  those variables, can behave differently under plain pytest; run
  `PYTHONHASHSEED=0 pytest .didibreak/tests` to match the harness.
- A test file's name comes from the function name; if your test suite has a
  file with the same name and you run both together, pytest may refuse to
  import one of them. Rename or move the generated file.

## Measured on real repositories

From the release-gate evaluation (`evaluation/README.md`, 38 scenarios in
seven pure-Python libraries, `gpt-6-luna`, 2026-11-09):

- **Precision:** 87% of `unexpected` findings (168 of 193) were real
  behavior changes. Every false alarm was an input of a type the function
  does not accept, in a function without type annotations (stub `.pyi`
  files are not read).
- **Recall:** of 22 reintroduced real bug fixes, 14 were reported. The
  misses needed non-literal arguments (iterators, parsed tokens), changed a
  generator, an instance method or a module-level regular expression, or
  got no valid cases in that run.
- **`new_function`:** 53 findings over two runs, none a real bug (wrong
  input types or slow huge inputs). This is why they never change the exit
  code.
- **Cost and time:** about $0.05 for all 38 runs; a run that checked a
  function took about 29 s (median), at most about 150 s.
- **Scope:** the libraries were chosen because their functions take
  strings, numbers and simple collections. Application code (request
  objects, ORM models, sessions, dates) will show more skipped functions
  and may show lower precision; this was not measured.
- Labels in the evaluation come from model labellers applying a written
  rubric, cross-checked by a second, independent labeller (60 of 60
  agree), not from human review.
