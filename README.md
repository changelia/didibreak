# didibreak

didibreak finds unintended behavior changes in code changes. It runs the old and
new versions of every changed function on the same generated inputs and reports
where the results differ, labelled against what the change was supposed to do.

## Why

AI coding agents change code that nobody reads line by line. Existing tests only
check what someone thought of, and agents often write tests that confirm their
own code. Behavior that nobody asserted can change silently. didibreak uses the
old version as the reference, so it needs no hand-written expected values.

## Status

In development. Nothing is released yet; the commands below work once the first
release is published.

## Install

Python 3.11+, Linux or macOS:

```bash
pip install didibreak
```

JavaScript / TypeScript: coming after Python 0.1.0.

```bash
npm install didibreak
```

## Quick start and example output

Added with the first working `didibreak check`; examples in these docs are
always real output.

## Documentation

- [Getting started (Python)](docs/getting-started-python.md)
- [How it works](docs/how-it-works.md)
- [Configuration (Python)](docs/configuration-python.md)
- [Output format](docs/output-format.md)
- [Use with AI agents](docs/ai-agents.md)
- [Providers and costs](docs/providers-and-costs.md)
- [Safety](docs/safety.md)
- [Limitations](docs/limitations.md)

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) · Changes: [CHANGELOG.md](CHANGELOG.md)
· License: [MIT](LICENSE)
