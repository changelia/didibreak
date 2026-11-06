# How it works

The pipeline, why the old version is the reference, and what is and is not detected.

The rest of this page (pipeline, the old version as reference) is written
together with the features it describes.

## Case generation

For each changed or new function that can be tested, didibreak asks the LLM
for input cases (`cases`, default 12), showing it the function's name,
signature, docstring and both versions of its code. The LLM proposes inputs
only; it never predicts results and never decides what changed.

- Every argument must be a Python literal: numbers, strings, bytes, `True`,
  `False`, `None`, and lists, tuples, dicts and sets of these. A case with
  anything else (a call, a name, an operator, an f-string) or an argument
  longer than 2,000 characters is dropped and counted as an invalid case.
- Cases with the same values are kept once; at most `cases` are used.
- A reply that is not valid JSON for the requested schema is asked for once
  more; if it fails again, the function is skipped.

| Skip reason | When |
| --- | --- |
| `invalid llm response` | The reply was unusable twice. |
| `no valid cases` | Every proposed case was invalid. |
| `llm unavailable` | The provider kept failing (rate limit, server or network error); this and all remaining functions are skipped. |
| `llm request rejected: <message>` | The provider refused this request (an HTTP 4xx other than 401, 403 and 404), for example because the prompt is too long; the run continues with the next function. |

A rejected API key (HTTP 401 or 403) or an unknown model (HTTP 404) stops the
run with exit code 2.

## Comparison rules

Each case runs on the base version and on the current version, twice on
each. Its outcome is what the function did: returned a value, raised an
exception, or timed out. The old version is the reference: a case is a
finding when the current version behaves differently.

| Situation | Result |
| --- | --- |
| A version gives different outcomes in its two runs | Dropped as flaky and counted; never a finding. |
| Both versions return values | Compared by value (see below); a difference is a finding with `high` confidence. |
| A returned value cannot be compared by value | Compared by type only; a different type is a finding with `low` confidence. |
| Both versions raise | Same exception type: no finding (the message is ignored). Different type: finding. |
| One version raises, the other returns | Finding. |
| One version times out | Finding. |
| Both versions time out | Dropped. |
| New function (no base version) | Exceptions and timeouts are findings, with label `new_function`. An exception type the function raises itself with a `raise` statement, in its own code or in functions of the same module it calls, is input validation and not a finding. Crashes (`didibreak.ProcessExited`) and timeouts are always findings. |

Intent never hides a finding; it only labels it `expected`, `unexpected` or
`unclear`.

### Comparing values

- Types must match: `1` and `1.0` differ, and so do `[1, 2]` and `(1, 2)`.
- Floats are equal when `math.isclose(before, after, rel_tol=1e-9,
  abs_tol=1e-12)` holds (`FLOAT_RELATIVE_TOLERANCE` and
  `FLOAT_ABSOLUTE_TOLERANCE` in `compare.py`), at any depth inside lists,
  tuples, sets and dicts. `NaN` equals `NaN`.
- Lists and tuples are compared in order; sets and dict keys in any order.
- Subclasses of the builtin types and `Enum` members are compared as
  described in [limitations.md](limitations.md#running-functions).

### Finding ids

Each finding has a 12-character id: the start of the SHA-256 of the
function's report name (`path/to/file.py::name`, relative to the repository)
and its arguments. The same function and arguments give the same id on every
run and every machine; `'a'` and `"a"` are the same argument.
