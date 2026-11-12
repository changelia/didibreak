# Use with AI agents

AI coding agents change code you may not read line by line. didibreak gives
them a check to run after each change: it reports behavior the change did
not intend, so the agent can fix it before handing the work back to you.

## Add the instruction

`didibreak init-agents` prints a snippet for your agent's instruction file.
It only prints: it never creates or edits `AGENTS.md`, `CLAUDE.md` or any
other file, and it needs no git repository and no API key.

```console
$ didibreak init-agents >> AGENTS.md
```

The snippet:

```markdown
## Behavior check
After changing Python functions, run:
    didibreak check --intent "<the user's request in one sentence>" --format json
If any finding has label "unexpected", fix the code so that behavior is preserved,
then run the check again. Report "unclear" findings to the user instead of guessing.
"new_function" findings do not fail the check; mention them to the user
and do not change code for them unless the user asks.
Exit code 2 means nothing could be checked (setup problem, provider down,
cost or token limit): report the error to the user.
If summary.functions_checked is 0, tell the user that nothing was checked and why.
Stop after 3 check rounds and report what is left.
```

Which file to put it in:

| Agent | File | Status |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` in the repository root | Should work, not verified |
| OpenAI Codex | `AGENTS.md` in the repository root | Should work, not verified |
| Cursor | `AGENTS.md` (or `CLAUDE.md`) in the repository root | Should work, not verified |

The file names come from each tool's documentation (checked 2026-11-09).
No agent has been tested running this loop yet; this table is updated
when one is. Any agent that reads an instruction file and can run shell
commands should be able to follow it.

The agent needs the same setup as you: didibreak installed in the
project's environment and an API key in its environment (see
[getting-started-python.md](getting-started-python.md)). With
`--format json` the cost confirmation is skipped; `max_cost` (default
$0.50) still limits each run.

## The loop

1. Make the change the user asked for.
2. Run `didibreak check --intent "<the user's request>" --format json`.
   The intent is what the user asked for, in one sentence. Commit messages
   since `--base` are added automatically.
3. Read the exit code:
   - `0`: no unexpected or unclear findings. Done. `new_function`
     findings never change the exit code; they are still in the report.
     If `summary.functions_checked` is `0`, every changed function was
     skipped by design (async, instance method, obvious I/O, blocked I/O, ...; the
     reasons are in `summary.skipped`): tell the user that nothing was
     checked and why.
   - `1`: there are findings; handle them by label (below).
   - `2`: didibreak could not check the change. Either it could not run at
     all (missing key, invalid config, not a git repository; stdout is
     empty), or functions were selected but none could be checked because
     of an error: the provider was unreachable, the cost or token limit was
     reached, or the modules failed to import (the report is on stdout, the
     reasons in `summary.skipped`). The error is on stderr. Report it to the
     user; do not retry the same command.
4. After fixing code, run the check again. Stop after 3 check rounds and
   report what is left instead of looping: every run costs LLM calls
   (cached cases make repeated runs cheaper, labels are never cached).

What to do with each label:

| Label | What it means | What the agent does |
| --- | --- | --- |
| `unexpected` | The intent does not cover this change. | Fix the code so the old behavior is preserved, run the reproducing test, then run the check again. |
| `unclear` | No intent, a vague intent, or labelling failed. | Do not guess. Report the finding to the user with `before` and `after` and ask whether the change is intended. If it is, run the check again with a more precise `--intent`. If it is not, fix it like an `unexpected` finding. |
| `expected` | The intent describes this change. | Nothing. Never undo it. |
| `new_function` | A new function raised an exception, crashed or timed out on an input. Never fails the check. | Mention it to the user (call and outcome). Do not change code for it unless the user asks. In the evaluation none of 53 was a real bug. |

## Reproducing tests

Run the reproducing tests **only for `unexpected` and `unclear`
findings**. Each test asserts what the code did **before** the change, so
it fails until the old behavior is back. That is the goal for an
`unexpected` finding, and for an `unclear` one once the user confirms the
change was not intended. Findings labelled `expected` get no test, so an
agent is never pushed to undo work the user asked for.

`test_file` in the JSON report names the file; the test name ends with the
finding's `id`, so one finding's test can be run alone. A real finding
(trimmed) and its test, from a check without an intent:

```json
{
  "findings": [
    {
      "id": "30040f8bc543",
      "function": "app/utils/phone.py::normalize_phone",
      "label": "unclear",
      "reason": "no intent was given (--intent or a commit message)",
      "args": [
        "'995 555 12 34 56'"
      ],
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
    }
  ]
}
```

```console
$ pytest -q .didibreak/tests/test_normalize_phone.py -k 30040f8bc543
...
FAILED .didibreak/tests/test_normalize_phone.py::test_normalize_phone_30040f8bc543
1 failed, 1 deselected in 0.01s
```

Rules for the agent:

- Never edit the generated tests to make them pass, and never copy them
  into the project's test suite unless the user asks.
- A passing reproducing test only shows that one input behaves as before;
  run the check again to see the whole picture.
- The check is the reference, not an old test. A finding that mixes a
  wanted and an unwanted change (a price that gained the requested
  thousands separator and lost its minus sign) keeps a failing test after
  the right fix, because the test asserts the whole old value. When the
  check no longer reports the finding as `unexpected`, its test is out of
  date.
- A test file is replaced only when a later run writes tests for the same
  function, so files from earlier runs stay. Deleting `.didibreak/tests/`
  clears them; it is generated and git-ignored.

The full report format is in [output-format.md](output-format.md).
