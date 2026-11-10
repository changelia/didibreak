# How it works

The pipeline, why the old version is the reference, and what is and is not detected.

## Pipeline

One `didibreak check` run:

1. **Find changed functions.** `git diff` between `--base` (default `HEAD`)
   and the working tree, including uncommitted and untracked files. Both
   versions of each changed file are parsed, and a function counts as
   changed when its code changes (formatting, comments and docstrings are
   ignored). New functions are found too; removed ones are listed.
2. **Skip what cannot be run.** Async functions, instance methods,
   generators and functions with obvious I/O are skipped with a reason
   ([limitations.md](limitations.md#functions-that-are-skipped)). Each
   remaining module is imported once in both versions, so a module that
   cannot be imported costs no tokens.
3. **Estimate the cost** and stop at `max_cost`
   ([providers-and-costs.md](providers-and-costs.md#cost-control)).
4. **Generate inputs.** The LLM proposes input cases as Python literals
   ([Case generation](#case-generation)). Cases are cached per function.
5. **Run both versions.** Every case runs on the base version and on the
   current version, twice each, in separate processes from temporary copies
   of the tree ([safety.md](safety.md#how-a-function-is-run)).
6. **Compare outcomes** with the [comparison rules](#comparison-rules).
   If no case differs, one refinement round asks for new cases.
7. **Label findings** against the intent: `expected`, `unexpected` or
   `unclear` ([Intent labels](#intent-labels)).
8. **Report** as text or JSON, write reproducing pytest files for
   `unexpected` and `unclear` findings, and exit with `0`, `1` or `2`
   ([output-format.md](output-format.md)).

## Why the old version is the reference

A test needs an expected value, and someone has to write it. didibreak
uses the code before the change instead: whatever the old version returned
or raised for an input is what the new version is expected to do, unless
the intent says the change was wanted. So the check needs no hand-written
assertions, and it also covers behavior nobody thought to test.

The price: didibreak finds *changes*, not bugs. A bug that was already in
the old version is reproduced faithfully and not reported, and every
intended change shows up as a finding, labelled `expected` when the intent
describes it.

## What is and is not detected

Detected: a different return value, a different exception type, raising
instead of returning (or the reverse), and a new timeout or crash, for the
inputs the LLM proposed.

Not detected:

- changes on paths none of the proposed inputs reaches;
- changes in functions that are skipped, and in side effects (files
  written, global state changed, output printed);
- changes in exception messages (only the type is compared);
- differences in values that cannot be compared by value, other than their
  type.

The full list is in [limitations.md](limitations.md).

## Case generation

For each changed or new function that can be tested, didibreak asks the LLM
for input cases (`cases`, default 12), showing it the function's name,
signature, docstring and both versions of its code. The LLM proposes inputs
only; it never predicts results and never decides what changed.

- Every argument must be a Python literal: numbers, strings, bytes, `True`,
  `False`, `None`, and lists, tuples, dicts and sets of these. A case with
  anything else (a call, a name, an operator, an f-string) or an argument
  longer than 2,000 characters is dropped and counted as an invalid case.
- For annotated parameters the LLM is asked for values of the annotated
  type only. If a finding's input still contradicts a simple annotation
  (builtin types, `None`, `Optional`/`Union`, `list`/`dict`/`tuple`/`set`
  of these) in every version, the finding is dropped and counted in
  `type_mismatch_dropped`. Unannotated parameters are not restricted.
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

### Refinement

When none of a function's cases shows a difference, didibreak asks the LLM
once more (`refine_rounds`, default 1, at most 3). The new request lists the
cases already tried and what each version did with them, and asks for
different cases aimed at the branches those cases did not reach. The new
cases go through the same validation, execution and comparison. A function
is not refined further once a round finds a difference, or when the LLM
proposes only cases that were already tried (`no new cases`).

## Intent labels

Every finding gets a label that says how it relates to what the change was
meant to do:

| Label | Meaning |
| --- | --- |
| `expected` | The intent explicitly describes this kind of change. |
| `unexpected` | The intent does not cover this change, or contradicts it. |
| `unclear` | The intent is vague, or the relation cannot be decided. |
| `new_function` | The function is new; there is no old behavior to compare with. |

The intent is the `--intent` text and the messages of all commits between
`--base` and HEAD, newest first (about 4,000 characters at most; older
messages are left out first), so a change one of those commits announced is
not labelled unexpected. One LLM request labels all findings of a run,
with a one-sentence reason each. The LLM never removes a finding and never
decides what changed; it only relates each measured difference to the
intent. Findings stay `unclear`, with the reason shown, when there is no
intent, when the labelling reply is unusable or the cost limit is reached,
and in `--cases-file` runs, which use no LLM. The exit code follows the
labels; see [output-format.md](output-format.md#exit-codes).

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
