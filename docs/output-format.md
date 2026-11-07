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
6. LLM notes: invalid cases dropped, refinement rounds, and the usage line
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
2 invalid cases dropped (not Python literals)
Refinement: 1 function(s) got 4 more cases
LLM: 3 calls · 3400 input tokens · 810 output tokens (400 reasoning) · cost $0.0018
```

## JSON report

The schema is [`spec/report.schema.json`](../spec/report.schema.json)
(`schema_version: 1`). Keys always come in the order below, and every object
is strict: a new key needs a new `schema_version`.

```json
{
  "schema_version": 1,
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
      "test_file": null
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
| `schema_version` | Always `1` for this format. |
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
| `findings[].test_file` | Reproducing pytest file, or `null` when none was written. |
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
