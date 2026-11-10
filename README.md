# didibreak

[![PyPI](https://img.shields.io/pypi/v/didibreak)](https://pypi.org/project/didibreak/)
[![CI](https://github.com/changelia/didibreak/actions/workflows/python.yml/badge.svg?branch=main)](https://github.com/changelia/didibreak/actions/workflows/python.yml)
[![License: MIT](https://img.shields.io/github/license/changelia/didibreak)](LICENSE)

didibreak finds unintended behavior changes in code changes. It runs the old and
new versions of every changed function on the same generated inputs and reports
where the results differ, labelled against what the change was supposed to do.

## Why

AI coding agents change code that nobody reads line by line. Existing tests only
check what someone thought of, and agents often write tests that confirm their
own code. Behavior that nobody asserted can change silently. didibreak uses the
old version as the reference, so it needs no hand-written expected values.

## Status

0.1.1 (alpha; first release 0.1.0 on 2026-11-10): Python only, Linux and macOS. The release
precision gate is met: in an evaluation on seven real libraries, 87% of `unexpected` findings
were real behavior changes ([evaluation/README.md](evaluation/README.md)).
The 7 libraries were chosen for literal-friendly functions, the labels are
model labels, and application code may score lower.

## Install

Python 3.11+, Linux or macOS:

```bash
pip install didibreak
```

JavaScript / TypeScript: not available yet; coming after Python 0.1.0 as
`npm install didibreak`.

## Quick start and example output

```bash
export OPENAI_API_KEY="sk-..."     # or ANTHROPIC_API_KEY (experimental, not live-verified)
didibreak check --intent "add thousands separators to prices"
```

didibreak compares your uncommitted changes with `HEAD`. It **runs your
changed functions**, old and new versions, on your machine; read
[safety.md](docs/safety.md) for what is isolated and what is not.

A real run with didibreak 0.1.0 on a change that added thousands separators
to a price formatter and also lost the minus sign (trimmed: 7 `UNEXPECTED`
and 5 `EXPECTED` findings in full; walk-through in
[Getting started](docs/getting-started-python.md)):

```text
didibreak 0.1.0 · working tree vs HEAD (94fdbfd8ff0b)
1 changed function(s) to check (0 new)
Estimated: up to 3 LLM calls (1 + up to 1 refinement + 1 labelling) with gpt-6-luna, ~4,614 input + ~7,200 output tokens, ~$0.0041 (limit $0.50)
12 cases · 12 behavior changes · 0 flaky dropped
  UNEXPECTED   prices.py::format_price(-250)
               before '-$2.50' → after '$2.50'
               Adding thousands separators does not imply removing the negative sign.
  EXPECTED     prices.py::format_price(100000)
               before '$1000.00' → after '$1,000.00'
               Adding a thousands separator to the price is the stated intent.
Reproducing tests: .didibreak/tests/test_format_price.py
LLM: 2 calls · 1469 input tokens · 1153 output tokens (460 reasoning) · cost $0.0007
```

## What it checks

**Works well on** functions whose inputs can be written as Python literals:
strings, numbers, booleans, `None`, and lists, tuples, dicts and sets of
these. Parsers, formatters, validators, converters and small utility
libraries are the sweet spot.

**Skipped in 0.1.x**, each listed in the report with its reason:

- `async` functions;
- instance methods (they need an object; `@staticmethod` and
  `@classmethod` are checked);
- generators;
- functions with obvious I/O: files, network, subprocesses, databases;
- typical FastAPI and Django handlers: async endpoints are skipped, and
  views that take request objects or query the database get no useful
  literal inputs.

Details: [limitations.md](docs/limitations.md).

For AI coding agents: `didibreak check --format json` and
`didibreak init-agents` ([Use with AI agents](docs/ai-agents.md)).

## Privacy

No telemetry. The only network requests go to the LLM provider you
configure, with your own API key; see
[what is sent](docs/providers-and-costs.md#what-is-sent-to-the-provider).

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
