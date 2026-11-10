# Getting started (Python)

Install didibreak, set an API key and run your first `didibreak check` on a
small example, then on your own project. Everything below was run on macOS
with Python 3.12 on 2026-11-10; the output is real.

## What you need

- Python 3.11 or newer, on Linux or macOS (Windows is not supported).
- `git`. didibreak compares your working tree with a git commit.
- An API key for OpenAI or Anthropic, or a local model server; see
  [providers-and-costs.md](providers-and-costs.md#setting-up-a-provider).
  The example below costs less than $0.01 with the default OpenAI model.

## 1. Install

didibreak is not on PyPI yet. Until the first release, install it from the
repository into a virtual environment:

```console
$ git clone https://github.com/changelia/didibreak.git
$ python3 -m venv .venv
$ . .venv/bin/activate
$ pip install ./didibreak/python
$ didibreak --version
didibreak 0.1.0.dev0
```

After the first release this becomes `pip install didibreak`.

didibreak runs your code with the Python it is installed in. For your own
project, install it into the project's virtual environment, or point it at
that environment with `--python .venv/bin/python` (see
[configuration-python.md](configuration-python.md)).

## 2. Set an API key

```console
$ export OPENAI_API_KEY="sk-..."
```

The variable holds the key only. With `ANTHROPIC_API_KEY` instead, didibreak
uses Anthropic. If the provider rejects the key, `check` stops with exit
code 2 at the first request, after the estimate:

```text
didibreak: error: the LLM provider rejected the API key (HTTP 401: Incorrect API key provided: ...); check OPENAI_API_KEY
```

## 3. A first check

Create a tiny project with one function and commit it:

```console
$ mkdir shop && cd shop && git init -q
$ cat > prices.py <<'EOF'
def format_price(cents: int) -> str:
    """Format an amount in cents as dollars: 1999 -> '$19.99', -250 -> '-$2.50'."""
    sign = "-" if cents < 0 else ""
    dollars, rest = divmod(abs(cents), 100)
    return f"{sign}${dollars}.{rest:02d}"
EOF
$ git add prices.py && git commit -q -m "Add format_price"
```

Now change it the way a hurried edit might: the request is "add thousands
separators", and the new code also loses the minus sign.

```console
$ cat > prices.py <<'EOF'
def format_price(cents: int) -> str:
    """Format an amount in cents as dollars: 1999 -> '$19.99', -250 -> '-$2.50'."""
    dollars, rest = divmod(abs(cents), 100)
    return f"${dollars:,}.{rest:02d}"
EOF
$ didibreak check --intent "add thousands separators to prices"
```

didibreak finds the changed function, prints an estimate and, on a
terminal, asks `Continue? [Y/n]` (press Enter). Then it asks the LLM for
inputs, runs both versions on them and prints the differences (trimmed;
the full run had 6 `UNEXPECTED` and 6 `EXPECTED` findings):

```text
didibreak 0.1.0.dev0 · working tree vs HEAD (cdb6d5f8113d)
1 changed function(s) to check (0 new)
Estimated: up to 3 LLM calls (1 + up to 1 refinement + 1 labelling) with gpt-6-luna, ~4,614 input + ~7,200 output tokens, ~$0.0041 (limit $0.50)
12 cases · 12 behavior changes · 0 flaky dropped
  UNEXPECTED   prices.py::format_price(-1)
               before '-$0.01' → after '$0.01'
               Adding thousands separators does not describe removing the negative sign.
  UNEXPECTED   prices.py::format_price(-250)
               before '-$2.50' → after '$2.50'
               Adding thousands separators does not describe removing the negative sign.
  UNEXPECTED   prices.py::format_price(-100000)
               before '-$1000.00' → after '$1,000.00'
               Although the output adds a thousands separator, it also removes the negative sign, which is not part of the stated intent.
  EXPECTED     prices.py::format_price(100000)
               before '$1000.00' → after '$1,000.00'
               The change adds a thousands separator to the price, as stated in the intent.
  EXPECTED     prices.py::format_price(123456789)
               before '$1234567.89' → after '$1,234,567.89'
               The change adds thousands separators to the price, as stated in the intent.
Reproducing tests: .didibreak/tests/test_format_price.py
  no test: prices.py::format_price(100000) (expected change)
  no test: prices.py::format_price(123456789) (expected change)
LLM: 2 calls · 1482 input tokens · 1161 output tokens (423 reasoning) · cost $0.0007
```

The exit code is `1` because there are `unexpected` findings.

How to read it:

- Each finding is one input where the old and the new version behave
  differently: `before` is the old result, `after` the new one.
- `EXPECTED` means the intent describes the change (the separators).
  `UNEXPECTED` means it does not (the lost minus sign): that is the bug.
  Without `--intent` and without a commit message that explains the change,
  findings are `UNCLEAR`. All labels are in
  [output-format.md](output-format.md#text-report).
- The cases differ from run to run, because the LLM proposes them.

## 4. Fix it and check again

`.didibreak/tests/test_format_price.py` holds one pytest test per
`unexpected` finding. Each asserts the old result, so it fails until the old
behavior is back (you need `pip install pytest`):

```console
$ pytest -q .didibreak/tests
...
6 failed in 0.02s
```

Put the sign back and run the check again:

```console
$ cat > prices.py <<'EOF'
def format_price(cents: int) -> str:
    """Format an amount in cents as dollars: 1999 -> '$19.99', -250 -> '-$2.50'."""
    sign = "-" if cents < 0 else ""
    dollars, rest = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{rest:02d}"
EOF
$ didibreak check --intent "add thousands separators to prices"
```

This time every finding is `EXPECTED` (for example `format_price(-100000)`:
`before '-$1000.00' → after '-$1,000.00'`) and the exit code is `0`.

The check is the reference, not the old test file:

- The test for `format_price(-100000)` still fails after this correct fix,
  because it asserts the whole old string, without the separator the
  request asked for. A finding that mixes a wanted and an unwanted change
  keeps a failing test; when the check no longer reports it as
  `unexpected`, the test is out of date.
- A test file is replaced only when a later run writes new tests for the
  same function, so old files stay until then. Delete `.didibreak/tests/`
  to clear them.

`.didibreak/` holds the tests and a cache of the generated cases, so an
unchanged function costs nothing to re-check (only the labelling request
is sent). The folder ignores itself, so it never shows up in `git status`.

## 5. Check your own project

From anywhere inside your git repository:

```console
$ didibreak check --intent "what you asked for, in one sentence"
$ didibreak check --base main          # everything changed since main
$ didibreak check --format json        # for AI agents and CI
```

- Only module-level functions, `@staticmethod` and `@classmethod` methods
  whose inputs can be written as Python literals are run. Other functions
  are listed as skipped with a reason; see
  [limitations.md](limitations.md#functions-that-are-skipped).
- didibreak runs your functions, so read [safety.md](safety.md) first:
  side effects of your own code still happen.
- At most 10 functions and $0.50 per run by default; see
  [configuration-python.md](configuration-python.md) for every flag and
  `pyproject.toml` key.
- To let an AI coding agent run the check after each change, see
  [ai-agents.md](ai-agents.md).
- Exit codes: `0` nothing unexpected or unclear, `1` unexpected or unclear
  findings, `2` a setup or config error (the message says what to fix).
