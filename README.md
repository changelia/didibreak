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

In development, not on PyPI yet. The precision gate for the first release is
met: in an evaluation on seven real libraries, 87% of `unexpected` findings
were real behavior changes ([evaluation/README.md](evaluation/README.md)).
The 7 libraries were chosen for literal-friendly functions, the labels are
model labels, and application code may score lower.

## Install

Python 3.11+, Linux or macOS. Until the first release, from the repository:

```bash
git clone https://github.com/changelia/didibreak.git
pip install ./didibreak/python
```

After the release: `pip install didibreak`.

JavaScript / TypeScript: not available yet; coming after Python 0.1.0 as
`npm install didibreak`.

## Quick start and example output

```bash
export OPENAI_API_KEY="sk-..."     # or ANTHROPIC_API_KEY
didibreak check --intent "add thousands separators to prices"
```

didibreak compares your uncommitted changes with `HEAD`. A real run on a
change that added thousands separators to a price formatter and also lost
the minus sign (trimmed; walk-through in
[Getting started](docs/getting-started-python.md)):

```text
didibreak 0.1.0.dev0 · working tree vs HEAD (cdb6d5f8113d)
1 changed function(s) to check (0 new)
Estimated: up to 3 LLM calls (1 + up to 1 refinement + 1 labelling) with gpt-6-luna, ~4,614 input + ~7,200 output tokens, ~$0.0041 (limit $0.50)
12 cases · 12 behavior changes · 0 flaky dropped
  UNEXPECTED   prices.py::format_price(-250)
               before '-$2.50' → after '$2.50'
               Adding thousands separators does not describe removing the negative sign.
  EXPECTED     prices.py::format_price(100000)
               before '$1000.00' → after '$1,000.00'
               The change adds a thousands separator to the price, as stated in the intent.
Reproducing tests: .didibreak/tests/test_format_price.py
LLM: 2 calls · 1482 input tokens · 1161 output tokens (423 reasoning) · cost $0.0007
```

For AI coding agents: `didibreak check --format json` and
`didibreak init-agents` ([Use with AI agents](docs/ai-agents.md)).

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
