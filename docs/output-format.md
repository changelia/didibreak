# Output format

`didibreak check` writes one report to stdout: text (the default) or JSON
(`--format json`). This page describes both, the finding labels and the exit
codes. The examples below are generated from the same data as the snapshot
tests in `python/tests/snapshots/`, and a test keeps this page in sync with
the code.

## Where the output goes

| Output | Text mode | JSON mode |
| --- | --- | --- |
| Header (version, base, changed functions) | stdout | not printed |
| Cost estimate (`Estimated: up to N LLM calls …`) | stdout | stderr |
| Cost confirmation prompt | stderr | not asked (`--format json` implies `--yes`) |
| Report | stdout | stdout, JSON only |
| Errors (exit code `2`) | stderr | stderr, no JSON is written |

So `didibreak check --format json > report.json` always gives a file with one
JSON document, or no document at all when the run fails with exit code `2`.
`-q` hides the estimate (it is not shown either when every case comes from
the cache); the header and the report are always printed.

## Text report

Order (Detailed Design section 7):

1. Header: version, base ref and its commit (12 characters), excluded files,
   files that could not be read, and how many changed functions will be
   checked. `-v` also lists each function, excluded file and function cut by
   `max_functions`.
2. The cost estimate, before any LLM request.
3. The summary line: cases run, behavior changes found and flaky cases dropped.
4. Findings grouped by label: `UNEXPECTED`, `UNCLEAR`, `EXPECTED`,
   `NEW-FUNCTION`. Each finding shows the call, the outcome before and after
   (a return value as its `repr`, an exception as `raises <type>`), and the
   reason for its label.
5. Skipped functions with their reasons, then removed functions.
6. `Reproducing tests:` with the test files written in this run, and a
   `no test:` line for each finding that has none (see below), then how many
   findings were dropped because an input contradicts the function's type
   annotations (only when there are any).
7. LLM notes: invalid cases dropped, refinement rounds, and the usage line
   (calls, tokens, cost) last. Runs with `--cases-file` send no requests and
   show none of these lines.

Labels are colored only when stdout is a terminal and `NO_COLOR` is not set.

Example (the part after the header and the estimate):

```text
14 cases · 3 behavior changes · 1 flaky dropped
  UNEXPECTED   app/utils/phone.py::normalize_phone('995 555 12 34 56')
               before '+995555123456' → after '+995995555123456'
               intent covers international numbers, not local numbers without plus
  EXPECTED     app/utils/phone.py::normalize_phone('+1 202 555 0100')
               before '+99512025550100' → after '+12025550100'
               intent covers international numbers
  NEW-FUNCTION app/text.py::initials('', strict=True)
               before (new function) → after raises builtins.ValueError
  skipped: app/db.py::save_user (obvious I/O: session.commit)
Removed: app/old.py::legacy
Reproducing tests: .didibreak/tests/test_normalize_phone.py
  no test: app/utils/phone.py::normalize_phone('+1 202 555 0100') (expected change)
  no test: app/text.py::initials('', strict=True) (new function: no base behavior to assert)
3 findings dropped (inputs outside the type annotations)
2 invalid cases dropped (not Python literals)
Refinement: 1 function(s) got 4 more cases
LLM: 3 calls · 3400 input tokens · 810 output tokens (400 reasoning) · cost $0.0018
```

## JSON report

The schema is [`spec/report.schema.json`](../spec/report.schema.json)
(`schema_version: 2`). Keys always come in the order below, and every object
is strict: a new key needs a new `schema_version`.

```json
{
  "schema_version": 2,
  "tool": {
    "name": "didibreak",
    "version": "0.1.0"
  },
  "base": {
    "ref": "HEAD",
    "sha": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
  },
  "intent": "Stated by the user: add international phone numbers",
  "findings": [
    {
      "id": "c2b1f5a53a6d",
      "function": "app/utils/phone.py::normalize_phone",
      "label": "expected",
      "reason": "intent covers international numbers",
      "confidence": "high",
      "args": [
        "'+1 202 555 0100'"
      ],
      "kwargs": {},
      "before": {
        "kind": "return",
        "type_name": "builtins.str",
        "repr": "'+99512025550100'"
      },
      "after": {
        "kind": "return",
        "type_name": "builtins.str",
        "repr": "'+12025550100'"
      },
      "test_file": null
    },
    {
      "id": "30040f8bc543",
      "function": "app/utils/phone.py::normalize_phone",
      "label": "unexpected",
      "reason": "intent covers international numbers, not local numbers without plus",
      "confidence": "high",
      "args": [
        "'995 555 12 34 56'"
      ],
      "kwargs": {},
      "before": {
        "kind": "return",
        "type_name": "builtins.str",
        "repr": "'+995555123456'"
      },
      "after": {
        "kind": "return",
        "type_name": "builtins.str",
        "repr": "'+995995555123456'"
      },
      "test_file": ".didibreak/tests/test_normalize_phone.py"
    },
    {
      "id": "0a1b2c3d4e5f",
      "function": "app/text.py::initials",
      "label": "new_function",
      "reason": "",
      "confidence": "high",
      "args": [
        "''"
      ],
      "kwargs": {
        "strict": "True"
      },
      "before": null,
      "after": {
        "kind": "exception",
        "type_name": "builtins.ValueError",
        "repr": "ValueError('not enough values to unpack (expected 2, got 0)')",
        "message": "not enough values to unpack (expected 2, got 0)"
      },
      "test_file": null
    }
  ],
  "summary": {
    "functions_checked": 2,
    "cases_run": 14,
    "findings": {
      "expected": 1,
      "unexpected": 1,
      "unclear": 0,
      "new_function": 1
    },
    "flaky_dropped": 1,
    "invalid_cases_dropped": 2,
    "type_mismatch_dropped": 3,
    "skipped": [
      {
        "function": "app/db.py::save_user",
        "reason": "obvious I/O: session.commit"
      }
    ],
    "removed": [
      {
        "function": "app/old.py::legacy"
      }
    ]
  },
  "usage": {
    "calls": 3,
    "input_tokens": 3400,
    "output_tokens": 810,
    "cost_usd": 0.0018
  }
}
```

| Key | Meaning |
| --- | --- |
| `schema_version` | Always `2` for this format (2 added `summary.type_mismatch_dropped`). |
| `tool` | `tool.name` is `didibreak`; `tool.version` is the installed version. |
| `base` | `base.ref` is `--base` as given; `base.sha` is the full commit it resolved to. |
| `intent` | The intent text used for labelling (`--intent` and the commit messages since the base), or `null`. |
| `findings` | One item per behavior change, in run order. |
| `findings[].id` | 12 hex characters, stable for the same function and arguments. |
| `findings[].function` | `path::qualname`, path relative to the repository. |
| `findings[].label` | `expected`, `unexpected`, `unclear` or `new_function`. |
| `findings[].reason` | Why the label was chosen; empty for new functions. |
| `findings[].confidence` | `high` when both outcomes were compared by value, `low` when only by type. |
| `findings[].args` | Positional arguments as Python literals. |
| `findings[].kwargs` | Keyword arguments as Python literals. |
| `findings[].before` | Outcome on the base, or `null` for a new function. |
| `findings[].after` | Outcome on the working tree. |
| `findings[].after.kind` | `return`, `exception` or `timeout` (the same keys for `before`). |
| `findings[].after.type_name` | Qualified type of the return value or exception. |
| `findings[].after.repr` | `repr` of the value or exception, at most 2,000 characters. |
| `findings[].after.message` | Exception message, at most 500 characters; only for exceptions. |
| `findings[].test_file` | Reproducing pytest file, relative to the repository root (absolute when `output_dir` is outside it), or `null`: findings labelled `expected`, new functions, a base version that timed out or ended the process, or a folder that could not be written. |
| `summary` | Counts for the whole run. |
| `summary.functions_checked` | Functions whose cases ran on both versions. |
| `summary.cases_run` | Cases run, refinement rounds included. |
| `summary.findings` | Findings per label; every label is present. |
| `summary.findings.expected` | Findings labelled `expected`. |
| `summary.findings.unexpected` | Findings labelled `unexpected`. |
| `summary.findings.unclear` | Findings labelled `unclear`. |
| `summary.findings.new_function` | Findings in new functions. |
| `summary.flaky_dropped` | Cases dropped because a version gave different results on two runs. |
| `summary.invalid_cases_dropped` | LLM cases rejected because an argument was not a Python literal. |
| `summary.type_mismatch_dropped` | Findings dropped because an input contradicts the function's type annotations (for example `bytes` for a `str` parameter). Only simple annotations are checked: builtin types, `None`, `Optional`/`Union`, and `list`, `dict`, `tuple`, `set` of these. |
| `summary.skipped` | Functions not checked. Files that could not be read appear with their path; functions cut by `max_functions` have the reason `limit`. |
| `summary.skipped[].function` | `path::qualname`, or a file path. |
| `summary.skipped[].reason` | Why it was skipped, for example `obvious I/O: session.commit` or `cost limit`. |
| `summary.removed` | Functions removed since the base. |
| `summary.removed[].function` | `path::qualname` on the base. |
| `usage` | LLM use of the run; all zero for `--cases-file` runs. |
| `usage.calls` | Requests sent; cached cases need none. |
| `usage.input_tokens` | Input tokens, cached input included. |
| `usage.output_tokens` | Output tokens, reasoning tokens included. |
| `usage.cost_usd` | Cost in US dollars; `0` for local models, `null` when the price is unknown. |

## Reproducing tests

Every finding whose base version returned a value or raised an exception,
except findings labelled `expected`, gets a pytest test in
`<output_dir>/tests/` (default `.didibreak/tests/`), one file per
function. Each test calls the function with the finding's inputs and
asserts what the **base** version did, so it passes on the base and fails
on your change. A failing test is the behavior change.

```text
$ didibreak check --cases-file ../cases.json
didibreak 0.1.0.dev0 · working tree vs HEAD (9d74d2b028c7)
1 changed function(s) to check (0 new)
3 cases · 2 behavior changes · 0 flaky dropped
  UNCLEAR      app/utils/phone.py::normalize_phone('+1 202 555 0100')
               before '+99512025550100' → after '+12025550100'
               no intent was given (--intent or a commit message)
  UNCLEAR      app/utils/phone.py::normalize_phone('995 555 12 34 56')
               before '+995555123456' → after '+995995555123456'
               no intent was given (--intent or a commit message)
Reproducing tests: .didibreak/tests/test_normalize_phone.py
$ cat .didibreak/tests/test_normalize_phone.py
# Reproducing tests for app/utils/phone.py::normalize_phone.
# Generated by didibreak 0.1.0.dev0 from base commit
# 9d74d2b028c79ecd60962143e34c6635aab09d0c.
# Each test asserts what the base version did; a failing test shows a
# behavior change. Safe to edit and move.

from app.utils.phone import normalize_phone


# Label: unclear (no intent was given (--intent or a commit message))
def test_normalize_phone_80d1e09b35bc() -> None:
    result = normalize_phone('+1 202 555 0100')
    assert result == '+99512025550100'


# Label: unclear (no intent was given (--intent or a commit message))
def test_normalize_phone_30040f8bc543() -> None:
    result = normalize_phone('995 555 12 34 56')
    assert result == '+995555123456'
$ pytest -q .didibreak/tests
...
2 failed in 0.02s
```

How the base outcome is asserted:

| Base outcome | Assertion |
| --- | --- |
| A value whose `repr` reads back as a Python literal | `assert result == <literal>`; `pytest.approx(..., rel=1e-9, abs=1e-12)` for floats and flat lists, tuples and dicts of numbers. When the new value compares equal (`1`, `1.0`, `True`), the `repr` is compared too. |
| Any other value | Only the qualified type is compared; the test says the check is weak. |
| An exception | `pytest.raises(...)` and the exact exception type. |
| Timeout or a process that ended | No test; listed as `no test:` in the text report. |
| New function | No test: there is no base behavior to assert. |
| Any outcome of a finding labelled `expected` | No test: the change matched the intent. |

- A test file is replaced each time its function has findings; test files
  of other functions are left alone.
- `conftest.py` in the same folder puts your import roots on `sys.path`,
  sets `TZ=UTC` (with `time.tzset()`) and calls `random.seed(0)` before
  each test, as didibreak's harness does, so plain `pytest` can run the
  files from the repository root. `PYTHONHASHSEED` is not reproduced: it
  must be set before Python starts.
  If you move a test into your own test suite, your suite's setup must
  make the module importable.
- Findings labelled `expected` get no test (`no test: ... (expected
  change)`): a test of the old behavior would fail on the change you asked
  for, and an AI agent could undo the work to make it pass.
- The folder ignores itself, so the tests never show up in `git status`,
  and plain `pytest` does not collect them unless you name the folder.

## Finding labels

| Label | Meaning |
| --- | --- |
| `unexpected` | The intent does not cover this change, or contradicts it. |
| `unclear` | No intent was given, the intent is vague, or labelling failed. |
| `expected` | The intent describes this kind of change. |
| `new_function` | The function did not exist on the base; the finding shows what it does now. |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No failing findings. |
| `1` | Failing findings: `unexpected`, `unclear` or `new_function` with the default `--fail-on unclear`; only `unexpected` with `--fail-on unexpected`. |
| `2` | Tool or configuration error: not a git repository, git missing, invalid flag or config value, missing API key. |
| `130` | Interrupted with Ctrl-C; temporary worktrees, copies and processes are removed first. |
