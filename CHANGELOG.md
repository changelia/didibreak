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

## JS/TS package

### Unreleased

Not started; follows Python 0.1.0.
