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
  missing and an LLM would be needed.
- Config-only key `temperature`; without it no temperature is sent.

## JS/TS package

### Unreleased

Not started; follows Python 0.1.0.
