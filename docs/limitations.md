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

The rest of this page is written together with the analysis features.
