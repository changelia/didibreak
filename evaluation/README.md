# Real-repository evaluation (task 21)

This folder holds the evaluation that decides whether didibreak 0.1.0 meets
its release gate (owner decision Q5): **at least 70% of `unexpected`
findings are real bugs** on the evaluation repositories.

Everything here was produced by real `didibreak check` runs with the default
OpenAI model (`gpt-6-luna`) on 2026-11-09. Nothing is simulated.

> **Scope of these numbers.** The libraries were chosen *because* they have
> many functions with literal-friendly arguments (strings, numbers, simple
> collections). Application code — for example FastAPI or Django apps, where
> functions take request objects, ORM models, sessions or dates — will show
> higher skip rates (instance methods, obvious I/O, no valid literal cases)
> and may show lower precision. These results do not measure that.

Two runs are recorded: the original task 21 run (`reports/`, `labels.json`)
and the task 21a re-run with the same plan after the wrong-type and import
changes (`rerun-21a/`). The task 21a results are at the end.

## Files

| Path | What it is |
| --- | --- |
| `plan.json` | Repositories (URL, commit evaluated), scenarios, budget |
| `patches/` | Seeded changes, one `git diff` per seeded scenario |
| `reports/<id>.json` | One saved run: scenario, command, exit code, seconds, stderr, the JSON report |
| `labels.json` | Hand label of every `unexpected` finding: `real` and a note |
| `../python/scripts/evaluate.py` | The runner and the summary |
| `owner-spot-check.md` | 10 re-run findings (seed 22) with sources and labels, for the owner's review |
| `rerun-37/` | Task 37 re-run after the runtime I/O guard: plan, reports and labels |
| `rerun-29/` | Task 29 re-run after async functions are checked: plan, reports and labels |
| `async-29/` | Task 29 measurement on an async library (asyncstdlib): plan, patches, reports, labels |
| `rerun-30/` | Task 30 re-run after instance methods are checked: plan, reports and labels |
| `methods-30/` | Task 30 measurement on a class-heavy library (boltons): plan, patches, reports, labels |
| `rerun-38/` | Task 38 re-run after constructor findings, the reply cap and the second case request: plan, reports and labels |
| `cost-38/` | Task 38 estimate vs actual cost on the asyncstdlib and boltons scenarios, before and after the change: plans, patches, reports (findings not labelled) |
| `rerun-31/` | Task 31 re-run of the task 21 plan with boundary cases (`after/`) and without (`before/`, `--boundary-cases 0`): plans, reports and labels |
| `boundary-31/` | Task 31 measurement on the asyncstdlib and boltons scenarios with and without boundary cases: plans, patches, reports and labels |

## Method

Seven public, actively maintained, pure-Python libraries tested with pytest,
with many functions that take strings, numbers or simple collections:
humanize, python-slugify, more-itertools, boltons, validators, packaging
and sqlparse (commits in `plan.json`).

Three kinds of scenario, each a `didibreak check --format json` run on an
uncommitted change against `HEAD`:

- **Replay** (22): a real bug-fix commit is applied in reverse, so the bug
  comes back. Intent: `Refactor the <module> module for readability;
  behavior must not change.` Every behavior difference is a regression the
  user did not ask for.
- **Seeded** (10): a hand-written change on the current `HEAD`. Seven are
  refactors meant to keep behavior (any `unexpected` finding there is a
  false alarm unless the refactor really changed behavior). Three add a
  small feature named in the intent and also contain a plausible mistake.
- **Forward** (6): a real commit that adds a public function, applied
  forward with its own commit subject as the intent. These measure
  `new_function` noise and labelling on real feature work.

Settings: defaults (`cases = 12`, `refine_rounds = 1`, `max_functions = 10`,
`timeout = 10`), `max_cost = 0.10` per run, Python 3.13, total budget $5.

### Labelling rubric

Every `unexpected` finding was labelled by hand, by reading the function,
the change and both outcomes:

- **Real**: a deterministic behavior change, on an input the function
  accepts (its annotations, docstring or obvious purpose), that the intent
  does not ask for.
- **Not real**:
  - *out of contract*: the input has a type the function does not accept
    (for example a float where an `int` count is expected) and only the
    error or the garbage result differs;
  - *intended*: the intent does ask for the change (a labelling mistake);
  - *artifact*: the difference comes from the harness or the environment,
    not from the code.

Precision = real / labelled `unexpected` findings, counted per finding as
in Q5. Findings cluster (one bug gives up to 12 findings), so a per-function
view is also given.

### Adaptations

- humanize imports `humanize/_version.py`, a file its build backend
  generates and git ignores. didibreak copies only the files git sees, so
  every humanize function failed with `import failed: ModuleNotFoundError`
  in both versions (one real run). The runner therefore commits a stub
  `_version.py` on top of each humanize base before the change. This is a
  product limitation; see Findings.

## Results

Generated by `scripts/evaluate.py summarize` (counts are findings):

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| humanize | 8 | 7 | 1 | 62 / 2 / 3 / 0 | 58 / 62 | 94% | $0.0122 |
| python-slugify | 2 | 2 | 0 | 12 / 0 / 0 / 0 | 12 / 12 | 100% | $0.0038 |
| more-itertools | 6 | 6 | 0 | 36 / 0 / 0 / 12 | 28 / 36 | 78% | $0.0104 |
| boltons | 7 | 5 | 2 | 23 / 0 / 1 / 24 | 23 / 23 | 100% | $0.0052 |
| validators | 7 | 7 | 0 | 35 / 0 / 0 / 0 | 34 / 35 | 97% | $0.0103 |
| packaging | 5 | 3 | 0 | 15 / 0 / 4 / 0 | 15 / 15 | 100% | $0.0038 |
| sqlparse | 3 | 2 | 1 | 12 / 0 / 0 / 0 | 0 / 12 | 0% | $0.0028 |
| **All** | 38 | 32 | 4 | 195 / 2 / 8 / 36 | 170 / 195 | 87% | $0.0486 |

**Release gate (Q5, ≥ 70%): met — 87% (170 of 195) of `unexpected`
findings are real.** Per function: 19 functions had `unexpected` findings;
18 had at least one real one, and one (sqlparse `remove_quotes`, seeded
refactor) had only false alarms. The 7 libraries were chosen for
literal-friendly functions, the labels are model labels, and application
code may score lower.

The 25 findings that are not real are all *out of contract*: bytes, lists,
tuples or dicts passed where a string or number is expected (17) and floats
or strings passed as integer counts or indexes (8). There were no *intended* or *artifact*
false alarms: no flaky case was dropped in 503 cases, and no difference came
from the harness.

Per-scenario detail is in `reports/`; the label and note of each finding is
in `labels.json`.

### What was found and missed

- **Replays (22):** the reintroduced bug was reported in 15. Two ran but
  missed it: more-itertools `cf186b5` needs an iterator argument and sqlparse
  `73c8ba3` needs parsed token lists; literals cannot express either. Five had
  nothing to check: the fix changed a generator (boltons `ead236e`,
  `3e9983d`), an instance method (sqlparse `f66d12c`) or a module-level regular
  expression rather than a function (packaging `0625596`, `8af7590`; such
  changes are transitive and not tested, Detailed Design §11).
- **Seeded refactors (7):** six produced no finding at all. sqlparse
  `remove_quotes` produced 12 out-of-contract false alarms: the refactor
  changes what happens for non-string inputs, which the LLM tried after the
  string cases showed no difference.
- **Seeded features with a mistake (3):** the mistake was reported as
  `unexpected` in all three. One labelling miss: in packaging, inputs with
  surrounding whitespace were labelled `expected` although the result was
  also lowercased (the mistake), so that part of the change hid inside an
  intended one.
- **Forward feature commits (6):** see `new_function` noise below; the two
  validators commits produced no finding, and the humanize commit could not
  be imported (`PackageNotFoundError`, it reads its version with
  `importlib.metadata`).

### `new_function` noise and implicit subclass exceptions

36 `new_function` findings in three new functions (more-itertools
`subfactorial`, boltons `ellipsize` and `human_readable_list`):

- 34 are exceptions on argument types the function does not accept
  (`TypeError`, `AttributeError`, `KeyError` for `None`, numbers, bytes,
  lists, sets or dicts where strings or integers are expected);
- 2 are timeouts of `subfactorial(10**8)` and `subfactorial(10**12)`, which
  are just slow;
- **0** are an implicit subclass of a type the function raises explicitly
  (`subfactorial` and `ellipsize` raise `ValueError`; no `ValueError`
  subclass was reported).

None of the 36 is a real bug. So the exact-type rule is not the source of
noise in this sample and relaxing it to subclasses would remove none of
these findings; the noise comes from inputs outside the function's
contract. With the default `--fail-on unclear` each of these runs exited 1
at the time; since task 22 `new_function` findings never change the exit
code (owner decision 2026-11-09).

### Skipped functions

Only 4 functions were skipped in 38 runs (generator 2, instance method 1,
`import failed` 1), because the scenarios were chosen in libraries with
literal-friendly functions. This sample says little about skip rates in
application code. Before the humanize adaptation, every humanize function
was skipped with `import failed: ModuleNotFoundError`.

### Speed and cost

- 62 LLM calls, 71,779 input and 84,289 output tokens, **$0.0486** in the
  saved reports, plus at most $0.1013 not in any report (`extra_spent` in
  `plan.json`): under $0.15 of the $5 budget.
- A run that checked a function took 28.8 s median and 149 s at most (three
  seeded runs took about 145 s; their reports show no timeouts in findings,
  so cases that timed out on both versions are the likely cause; not
  verified).
- The temporary copy of the working tree is not a bottleneck
  (`evaluate.py copy-time`, macOS, 2026-11-09):

| Repository | Files copied | Seconds |
| --- | --- | --- |
| more-itertools | 39 | 0.03 |
| python-slugify | 44 | 0.04 |
| humanize | 89 | 0.06 |
| sqlparse | 94 | 0.05 |
| boltons | 114 | 0.05 |
| validators | 132 | 0.05 |
| packaging | 140 | 0.05 |
| didibreak | 145 | 0.06 |
| django (shallow clone) | 7,097 | 2.12 |

## Proposals (owner decision needed)

1. **Inputs outside the contract** (all 25 false alarms, all 36
   `new_function` findings): ask the LLM for inputs that match the
   parameters' type annotations and docstring, and/or drop findings whose
   arguments contradict a parameter annotation (e.g. `bytes` for `str`).
2. **Keep the exact-type rule** for explicit raises: no implicit-subclass
   noise was measured.
3. **Generated version files:** copy git-ignored `_version.py` /
   `version.py` files next to an import root into both trees, or document
   the limitation only (done in `docs/limitations.md`).
4. **Import before generating cases:** a function whose module cannot be
   imported still costs one LLM call (humanize, twice); an import check
   before case generation would save it.
5. **Tree copy:** no change needed.

## Task 21a re-run (2026-11-09)

Changes since task 21 (owner decisions on the task 21 proposals): case
generation asks for values of the annotated type (prompt version 2);
findings whose inputs contradict a simple annotation in every version are
dropped and counted (`summary.type_mismatch_dropped`); every module is
imported in both versions before any LLM request. Same plan, same rubric,
labels in `rerun-21a/labels.json`.

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| humanize | 8 | 7 | 1 | 60 / 2 / 4 / 0 | 60 / 60 | 100% | $0.0104 |
| python-slugify | 2 | 2 | 0 | 12 / 0 / 0 / 0 | 12 / 12 | 100% | $0.0033 |
| more-itertools | 6 | 6 | 0 | 36 / 0 / 0 / 6 | 23 / 36 | 64% | $0.0107 |
| boltons | 7 | 5 | 2 | 22 / 0 / 2 / 11 | 22 / 22 | 100% | $0.0068 |
| validators | 7 | 6 | 1 | 34 / 0 / 0 / 0 | 34 / 34 | 100% | $0.0098 |
| packaging | 5 | 3 | 0 | 17 / 0 / 3 / 0 | 17 / 17 | 100% | $0.0041 |
| sqlparse | 3 | 2 | 1 | 12 / 0 / 0 / 0 | 0 / 12 | 0% | $0.0036 |
| **All** | 38 | 31 | 5 | 193 / 2 / 9 / 17 | 168 / 193 | 87% | $0.0487 |

| Measure | Task 21 | Task 21a |
| --- | --- | --- |
| Precision (real / unexpected) | 87% (170 / 195) | **87% (168 / 193)** |
| `new_function` findings (real bugs) | 36 (0) | **17 (0)** |
| Findings dropped by the annotation check | — | 0 |
| Replayed bug found (of 22) | 15 | **14** |
| LLM calls on unimportable modules | 2 | 0 |
| Cost of the run | $0.0486 | $0.0487 |

What changed and why precision did not move:

- **All 25 false alarms of the re-run are in unannotated functions**
  (sqlparse `remove_quotes` 12, more-itertools `exactly_n` 10 and
  `nth_permutation` 3; more-itertools keeps its annotations in stub files,
  which didibreak does not read). The annotation check cannot act there by
  design (unannotated functions are unchanged), so it dropped nothing.
- In annotated functions there were **no** false alarms in the re-run. The
  four task 21 false alarms in humanize `ordinal` (lists, bytes for a
  `NumberOrString` parameter, an alias the check does not resolve) did not
  recur: the prompt now asks for annotated types. Applied to the task 21
  reports, the check would have dropped one `unexpected` finding (validators
  `_isin_checksum([0])`, a list for a `str`) and 3 of the 36 `new_function`
  findings (boltons `human_readable_list`, the only annotated new function).
- `new_function` findings halved (36 → 17), all still wrong-type inputs or a
  slow huge input in unannotated new functions (`ellipsize`,
  `subfactorial`); none real, none an implicit subclass of an explicitly
  raised type.
- Recall: the validators `cron` replay was missed this time because all 12
  proposed cases were invalid literals (`no valid cases`); in task 21 it was
  found. This is run-to-run variance of the LLM, not a code change in that
  path. The other 21 replays behaved as in task 21.
- The import check removed the LLM call for the humanize forward commit
  (`PackageNotFoundError`): 0 calls instead of 1.

### Independent label check

A separate agent that had not seen these labels labelled a random sample
(seed 21) of **60** of the 193 `unexpected` findings from the function
sources, the inputs, both outcomes, the intent and the rubric
(`rerun-21a/independent/`). It agreed on **60 of 60** (Cohen's kappa 1.0);
precision recomputed with its labels where they disagree stays **87.0%
(168 / 193)**. It named borderline cases it still labelled real:
a too-short string for the private ISIN checksum, `exactly_n` at
`sys.maxsize`, `IndexError` → `ValueError` on already-invalid sizes, and
`ordinal(',123')`. Both labellers are models applying the same written
rubric; a human review of the borderline cases is still advisable.

`owner-spot-check.md` (task 22) lists 10 more findings drawn with seed 22,
with full function sources, inputs, both outcomes and a third label for
the owner's own check: 10 of 10 agree with the saved labels.

### Spend

Task 21 saved reports $0.0486, task 21 unrecorded at most $0.1013, task 21a
saved reports $0.0487, and $0.0023 for two task 21a runs that ran twice
(two parallel runners overlapped; the second result was kept): **about
$0.20 of the $5 budget**.

## Task 37 re-run (2026-11-15)

Run after the runtime I/O guard (task 36) and the robustness fixes
(task 37), at commit `ba4afee` of branch `task-37-robustness`, to measure
how many functions the guard skips as `blocked: <event>` on real projects
and whether precision moved. Same plan, same rubric, default model
(`gpt-6-luna`), Python 3.13, macOS; reports and labels in `rerun-37/`.
Labels of the 25 findings with the same inputs as in task 21a were reused;
the other 150 were labelled by the model that ran the evaluation.

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| humanize | 8 | 6 | 2 | 40 / 2 / 3 / 0 | 40 / 40 | 100% | $0.0200 |
| python-slugify | 2 | 2 | 0 | 12 / 0 / 0 / 0 | 12 / 12 | 100% | $0.0031 |
| more-itertools | 6 | 6 | 0 | 36 / 0 / 0 / 5 | 28 / 36 | 78% | $0.0182 |
| boltons | 7 | 3 | 4 | 9 / 0 / 3 / 0 | 9 / 9 | 100% | $0.0057 |
| validators | 7 | 7 | 0 | 46 / 0 / 0 / 0 | 46 / 46 | 100% | $0.0110 |
| packaging | 5 | 3 | 0 | 20 / 0 / 3 / 0 | 20 / 20 | 100% | $0.0044 |
| sqlparse | 3 | 2 | 1 | 12 / 0 / 0 / 0 | 0 / 12 | 0% | $0.0026 |
| **All** | 38 | 29 | 7 | 175 / 2 / 9 / 5 | 155 / 175 | 89% | $0.0650 |

| Skip reason | Count |
| --- | --- |
| no valid cases | 3 |
| generator | 2 |
| instance method | 1 |
| import failed | 1 |

| Measure | Task 21a | Task 37 |
| --- | --- | --- |
| Functions skipped as `blocked: <event>` | — (no guard) | **0** |
| Functions checked / skipped | 31 / 5 | 29 / 7 |
| Precision (real / unexpected) | 87% (168 / 193) | **89% (155 / 175)** |
| Replayed bug found (of 22) | 14 | 13 |
| `new_function` findings (real bugs) | 17 (0) | 5 (0) |
| Cost of the run | $0.0487 | $0.0650 |

What the numbers say:

- **The guard skipped nothing.** No function in the 38 runs was skipped
  with `blocked:`; there is no event to list. These libraries do no I/O in
  the changed functions or at import, so this says little about
  application code (see the scope note at the top).
- **Two fewer functions were checked, and none of that is the guard.**
  Three runs ended with `no valid cases` (every proposed case was an
  invalid literal): boltons `singularize` (replay `1e61524`), boltons
  `ellipsize` (forward `673e010`) and humanize `metric` (replay
  `e46732e`); all three were checked in task 21a. The validators `cron`
  replay, which had `no valid cases` in task 21a, was checked this time.
  To tell a regression from model variance, the boltons `singularize`
  scenario was run 10 more times at `ba4afee` and 10 times at `main`
  (`45d0814`), without the cache: 1 of 10 had `no valid cases` on each
  side. So this is run-to-run variance of the model, at a rate of about
  1 run in 10 for this function, not a change in this branch. A retry
  when every case is invalid would remove most of it (not done here).
- **Precision did not drop:** 89% against the 87% baseline, inside the
  run-to-run noise. All 20 false alarms are again *out of contract* and
  in unannotated functions: sqlparse `remove_quotes` 12 (bytes, lists,
  tuples, dicts for a string), more-itertools `exactly_n` 4 (float count)
  and `nth_permutation` 4 (float size, `None` index). Seven `exactly_n`
  findings with a negative integer count are labelled real (the type is
  accepted and the result changed from `False` to `ValueError`); they are
  borderline, and with them as false alarms precision is 85% (148 / 175).
- Recall: 13 of 22 replays. Lost to `no valid cases`: boltons `1e61524`
  and humanize `e46732e`; gained: validators `cron` (`aa5d83b`).
- The humanize forward run now exits 2 instead of 0: its only function
  cannot be imported, and since task 35b a run where nothing could be
  checked for an error reason exits 2.
- 62 LLM calls, 76,442 input and 114,994 output tokens; a run that
  checked a function took 24.6 s median and 151.7 s at most.

Spend: $0.0650 in the saved reports, plus about $0.02 not in any report
(the 20 variance runs and one debugging run). Total for all evaluation
work so far: about $0.29 of the $5 budget.

## Task 29: async functions (2026-11-22)

Async functions (`async def`) are run with `asyncio.run` since task 29
instead of being skipped. Both measurements ran at commit `09b00c9` of
branch `task-29-async`, with the default model (`gpt-6-luna`), Python
3.13, macOS, the same rubric. Labels of findings with the same inputs as in
task 21a or task 37 were reused; the others were labelled by the model that
ran the evaluation (agent labels, not independently checked).

### Re-run of the task 21 plan (`rerun-29/`)

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| humanize | 8 | 7 | 1 | 56 / 0 / 4 / 0 | 56 / 56 | 100% | $0.0115 |
| python-slugify | 2 | 1 | 1 | 12 / 0 / 0 / 0 | 12 / 12 | 100% | $0.0027 |
| more-itertools | 6 | 6 | 0 | 34 / 0 / 0 / 11 | 26 / 34 | 76% | $0.0093 |
| boltons | 7 | 5 | 2 | 22 / 0 / 2 / 1 | 22 / 22 | 100% | $0.0146 |
| validators | 7 | 6 | 1 | 23 / 0 / 0 / 0 | 23 / 23 | 100% | $0.0098 |
| packaging | 5 | 3 | 0 | 19 / 0 / 4 / 0 | 19 / 19 | 100% | $0.0041 |
| sqlparse | 3 | 2 | 1 | 12 / 0 / 0 / 0 | 0 / 12 | 0% | $0.0028 |
| **All** | 38 | 30 | 6 | 178 / 0 / 10 / 12 | 158 / 178 | 89% | $0.0547 |

| Skip reason | Task 37 (before) | Task 29 (after) |
| --- | --- | --- |
| no valid cases | 3 | 2 |
| generator | 2 | 2 |
| instance method | 1 | 1 |
| import failed | 1 | 1 |
| `async function` / `blocked:` | 0 / 0 | 0 / 0 |
| **All** | 7 | 6 |

- **The release gate still holds: 89% (158 / 178)** of `unexpected`
  findings are real (gate 70%, baseline 87%). Four `exactly_n` findings
  with a negative integer count are labelled real but borderline; counted
  as false alarms, precision is 86.5% (154 / 178). All 20 false alarms are
  again *out of contract*, in unannotated functions: sqlparse
  `remove_quotes` 12 (bytes for a string), more-itertools `exactly_n` 5
  (float counts) and `nth_permutation` 3 (an index that is `None`, a
  string or a list).
- **Skip counts did not move because of async:** these libraries have no
  changed `async def` function in any scenario, so no skip was removed and
  none added. The one fewer skip is `no valid cases` (2 instead of 3, other
  functions this time: validators `cron` and python-slugify
  `smart_truncate`), the model variance measured in task 37.
- Replays found: 14 of 22 (13 in task 37). 61 LLM calls, 74,009 input and
  94,917 output tokens; a run that checked a function took 23.7 s median
  and 147.6 s at most.

### An async library: asyncstdlib (`async-29/`)

The evaluation libraries have almost no async code, so a library made of
`async def` functions was added: [asyncstdlib](https://github.com/maxfischer2781/asyncstdlib)
(async versions of `min`, `max`, `sorted`, `sum`, `dict`, ..., which also
take plain lists, so literals reach them). Chosen because its functions
take literal-friendly arguments and its history has behavior fixes in
`async def` functions; application code (FastAPI handlers that take
requests and sessions) would mostly get `no valid cases` or obvious I/O
skips and says less about the comparison. 10 scenarios at `0f01ce7`:

- 6 replays of real commits: `3879b3d` (`max` returned the last of equal
  items, a bug fix), `fa54340`, `fb1dca4`, `730c981` (min/max and sorted
  changes with no visible effect on literals), `b537d07` and `d5363de`
  (`heapq.merge` and `map`, async generators);
- 4 seeded changes: refactors of `sum` and of `all`/`any` that keep
  behavior, `sorted()` that should put `None` last but also drops
  duplicates, and `dict()` that should accept a mapping but also stops
  letting keywords override pairs.

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| asyncstdlib | 10 | 9 | 3 | 29 / 0 / 7 / 0 | 29 / 29 | 100% | $0.0391 |

| Skip reason | Count |
| --- | --- |
| async generator | 2 |
| instance method | 1 |

- **All 9 checked functions are `async def`**; before task 29 all of them
  would have been skipped as `async function` (0 checked, 12 skipped).
- The reintroduced `max` bug was found: 12 findings such as
  `_min_max([1, True], None, True)` returning `True` instead of `1`, and
  sets that are not subsets of each other returning the later one.
- Both seeded mistakes were found (6 `dict` and 11 `sorted` findings, one
  of them borderline: with `reverse=True`, `None` comes first), and the
  intended parts were labelled `expected` (7 findings).
- The two refactors and the three replays without a visible change gave
  **no finding**: no false alarm on async code in this set.
- One run (`sum` refactor) took 297 s and $0.025, six times its estimate:
  the model's replies were cut off and retried (4 calls, 49,434 output
  tokens); `max_cost` (0.10) was not reached.

Spend for task 29: $0.0547 (re-run) + $0.0391 (asyncstdlib) + $0.0008
(live run) = about $0.095. Total for all evaluation work so far: about
$0.38 of the $5 budget.

## Task 30: instance methods (2026-11-22)

Instance methods are run since task 30: each case builds the instance from
literal constructor arguments, calls the method, and compares the result
and the instance's state after the call. Both measurements ran at commit
`3cb44c2` of branch `task-30-methods`, with the default model
(`gpt-6-luna`), Python 3.13, macOS, the same rubric. Labels of findings
with the same inputs as in an earlier run were reused; the others are
agent labels, not independently checked.

### Re-run of the task 21 plan (`rerun-30/`)

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| humanize | 8 | 6 | 2 | 48 / 1 / 2 / 0 | 48 / 48 | 100% | $0.0267 |
| python-slugify | 2 | 2 | 0 | 12 / 0 / 0 / 0 | 12 / 12 | 100% | $0.0032 |
| more-itertools | 6 | 6 | 0 | 35 / 0 / 0 / 8 | 23 / 35 | 66% | $0.0101 |
| boltons | 7 | 3 | 4 | 10 / 0 / 1 / 0 | 10 / 10 | 100% | $0.0053 |
| validators | 7 | 7 | 0 | 35 / 0 / 0 / 0 | 35 / 35 | 100% | $0.0099 |
| packaging | 5 | 3 | 0 | 19 / 0 / 4 / 0 | 19 / 19 | 100% | $0.0041 |
| sqlparse | 3 | 3 | 0 | 12 / 0 / 0 / 0 | 0 / 12 | 0% | $0.0055 |
| **All** | 38 | 30 | 6 | 171 / 1 / 7 / 8 | 147 / 171 | 86% | $0.0648 |

| Skip reason | Task 29 (before) | Task 30 (after) |
| --- | --- | --- |
| no valid cases | 2 | 3 |
| generator | 2 | 2 |
| instance method | 1 | 0 |
| import failed | 1 | 1 |
| **All** | 6 | 6 |

- **The release gate still holds: 86% (147 / 171)** of `unexpected`
  findings are real (gate 70%, baseline 87%); 83% if five borderline
  negative-count findings in more-itertools `exactly_n` are counted as
  false alarms. All 24 false alarms are *out of contract*, in unannotated
  functions, as in every earlier run: sqlparse `remove_quotes` 12, and
  float counts or non-integer indexes in more-itertools `exactly_n` 6 and
  `nth_permutation` 6.
- The one instance method of the plan (sqlparse
  `NameAliasMixin.get_real_name`, replay `f66d12c`) is now checked instead
  of skipped. It got 1 case and no finding: the bug needs parsed tokens,
  which literals cannot build. The `no valid cases` skips (humanize
  `metric`, boltons `singularize`, `ellipsize`) are the model variance
  measured in task 37.
- Replays found: 13 of 22 (14 in task 29). 64 LLM calls, 81,508 input and
  113,971 output tokens; median 27.8 s, at most 215.7 s.

### A class-heavy library: boltons (`methods-30/`)

boltons' container and statistics classes (`IndexedSet`,
`OrderedMultiDict`, `OneToOne`, `Stats`, `BarrelList`, `_ComplementSet`)
are built from plain lists and dicts, so literals can build them, their
methods change `self`, and their history has many fixes in methods. 15
scenarios at `d31d821`:

- 11 replays of real fixes in these classes: `8a49b74` (`update_extend`
  with itself), `1cdc0e9` (`Stats` histograms with zero spread),
  `a180020` (`IndexedSet.update` with several iterables), `a1ea103`
  (`addlist` with an iterator), `ec1ff9f` (`_ComplementSet` comparisons),
  `d0a284f` (`IndexedSet` out-of-range indexes), `609cabe`
  (`iter_slice` after removals), `c463d16` (`OrderedMultiDict.__eq__`),
  `f9c4f30` (`BarrelList.sort` with more than one internal list),
  `6cac49c` (`OneToOne.update` with an empty iterable), `8177b93`
  (`addlist` with an empty list, `poplast` with a default);
- 4 seeded changes: refactors of `IndexedSet.add` and
  `OrderedMultiDict.getlist` that keep behavior; a "faster"
  `IndexedSet.discard` that forgets to compact the set (a change in the
  state only); `Stats.get_quantile` that should accept percentages but
  also turns `1` (the maximum) into 1%.

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| boltons | 15 | 16 | 5 | 91 / 0 / 9 / 0 | 69 / 91 | 76% | $0.0574 |

| Skip reason | Count |
| --- | --- |
| dunder method | 5 (`__eq__` twice, `__le__`, `__ge__`, `__getitem__`) |

- **All 16 checked functions are instance methods**; before task 30 all
  of them, and the 5 dunder methods, would have been skipped as
  `instance method` (0 checked, 21 skipped).
- **No case was dropped for construction** (`construction_dropped` 0 in
  every run): the LLM's constructor arguments built every instance.
- **Found:** the reintroduced bugs in `Stats._get_bin_bounds` (12
  findings, `ZeroDivisionError`), `OneToOne.update` (12,
  `UnboundLocalError`), `poplast` with a default (12), `IndexedSet.update`
  (11; for hashable arguments the result is `None` in both versions and
  the change is only in the state: the iterables are added as items),
  `IndexedSet._get_real_index` (9) and `iter_slice` (3); and the seeded
  `discard` mistake (9, state only) and `get_quantile(1)` (1).
- **Not found:** `update_extend` with itself (a literal cannot be the
  instance itself), `addlist` with an iterator (literals are never
  iterators), `BarrelList.sort` with more than one internal list (needs
  more than 1,520 items, longer than an argument may be), the three
  dunder-method fixes (skipped by design). The two refactors gave no
  finding.
- **Precision 76% (69 / 91), above the gate.** The 22 false alarms: 16
  `addlist` findings where the value is not an iterable (`0`, `None`,
  `False`; out of contract), 3 float indexes, 1 unhashable item for
  `discard`, `get_quantile(True)` (a bool), and `get_quantile('50')`,
  which the intent asks for (a labelling mistake by the model).
- Two runs (`f9c4f30`, `getlist` refactor) took more than 200 s and
  $0.017 each, four times their estimate: cut-off model replies retried,
  as in task 29; `max_cost` was not reached.

Live run on the `method_state_regression` fixture (default model): 12
cases, 9 `unexpected` findings with a different state and the same
result (`None`), 1 `expected`, 2 calls, $0.0010.

Spend for task 30: $0.0648 (re-run) + $0.0574 (boltons) + $0.0010 (live
run) = about $0.12. Total for all evaluation work so far: about $0.52 of
the $5 budget.

## Reproduce

```console
$ git clone <each repository in plan.json> repos/<key>
$ cd python
$ export OPENAI_API_KEY=...
$ uv run python scripts/evaluate.py run ../evaluation/plan.json ../repos <python>
$ uv run python scripts/evaluate.py summarize ../evaluation/plan.json
```

`<python>` is an interpreter with the libraries' runtime dependencies
(only `text-unidecode` for python-slugify). Saved reports are not run again.

## Task 38: constructors, reply cap and a second case request (2026-11-23)

Task 38 reports a constructor that fails in one version only as a
`Class.__init__` finding, checks a changed `__init__` by building the
instance, caps case-generation replies at 700 output tokens per requested
case (8,400 for 12 cases, was 16,000), and asks once more when a reply has
no valid case. Default model (`gpt-6-luna`), Python 3.13, macOS, the same
rubric. Labels of findings with the same inputs as in an earlier run were
reused (74); the other 122 are agent labels, not independently checked.

### Re-run of the task 21 plan (`rerun-38/`, commit `48921a8`)

| Repository | Runs | Checked | Skipped | Unexpected / unclear / expected / new_function | Real / labelled unexpected | Precision | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| humanize | 8 | 7 | 1 | 58 / 0 / 5 / 0 | 58 / 58 | 100% | $0.0125 |
| python-slugify | 2 | 2 | 0 | 12 / 0 / 0 / 0 | 12 / 12 | 100% | $0.0037 |
| more-itertools | 6 | 6 | 0 | 36 / 0 / 0 / 7 | 31 / 36 | 86% | $0.0103 |
| boltons | 7 | 5 | 2 | 22 / 0 / 2 / 1 | 22 / 22 | 100% | $0.0069 |
| validators | 7 | 7 | 0 | 42 / 0 / 0 / 0 | 42 / 42 | 100% | $0.0104 |
| packaging | 5 | 3 | 0 | 14 / 0 / 4 / 0 | 14 / 14 | 100% | $0.0087 |
| sqlparse | 3 | 3 | 0 | 12 / 0 / 0 / 0 | 0 / 12 | 0% | $0.0046 |
| **All** | 38 | 33 | 3 | 196 / 0 / 11 / 8 | 179 / 196 | 91% | $0.0572 |

| Skip reason | Task 30 | Task 38 |
| --- | --- | --- |
| no valid cases | 3 | 0 |
| generator | 2 | 2 |
| import failed | 1 | 1 |
| **All** | 6 | 3 |

- **The release gate holds: 91% (179 / 196)** of `unexpected` findings are
  real (gate 70%); 88% if the five negative-count findings in
  more-itertools `exactly_n` are counted as false alarms. The 17 false
  alarms are *out of contract* as before: sqlparse `remove_quotes` with a
  value that is not a string 12, more-itertools `exactly_n` with a float
  count 5.
- **No function was lost to `no valid cases`** (3 in task 30, 2 in task
  29): the second request did its job, and those functions were checked.
  Replays found: 15 of 22 (13 in task 30). 67 LLM calls, 85,690 input and
  97,977 output tokens; median 25.4 s, at most 83.5 s.
- No constructor finding: the plan has no class whose construction
  changed.

### Estimate vs actual cost (`cost-38/`)

The 25 asyncstdlib (task 29) and boltons (task 30) scenarios, run twice:
`before/` at `bb7af7d` (constructor findings, without the cap and the
second request) and `after/` at `48921a8`. 21 runs per side made LLM
calls; the others stop before any (import failures, no testable change).

| | Before | After |
| --- | --- | --- |
| Actual / estimated cost, all runs | $0.0738 / $0.1043 (0.71) | $0.0706 / $0.1043 (0.68) |
| Most expensive run against its estimate | 3.9 times (`boltons-replay-f9c4f30`, $0.0162) | 2.3 times (`boltons-seeded-refactor-indexedset_add`, $0.0094) |
| Runs above 2 times their estimate | 2 | 2 |

- **What made runs expensive** (tasks 29 and 30: 4 to 6 times): a reply
  that ran away to the output cap, then its retry ran away too. In 150
  earlier runs a normal case-generation reply used at most about 4,100
  output tokens (median 1,300); the cut-off ones used exactly 16,000.
  Such replies are model variance. Before, 3 of 21 runs used 19,400 to
  32,000 output tokens (one lost a function to two cut-off replies);
  after, the same scenario lost its function again, now at 16,800 tokens,
  and two other runs used 13,000 to 18,100. A report gives only the run's
  total, so single cut-offs cannot be counted exactly.
- **Chosen approach: a smaller cap, not a larger one.** A larger cap
  would only let runaway replies cost more; it would not make them
  usable. With 8,400 tokens the same `f9c4f30` run (both replies cut
  off) cost $0.0086 instead of $0.0162. An expected retry share in the
  estimate was not added: over all runs the estimate is already above
  the actual cost (0.68), the per-case output estimate (180 tokens) sits
  above what replies use, and a share would not help the single runs
  that go over. Every request's cap also stays within what is left of
  `max_tokens` and `max_cost`, so the limits hold even then.
- The second case request is included in "after": it is checked against
  both limits before it is sent.
- Cost of task 38 measurements: rerun $0.0572, cost runs $0.0738 +
  $0.0706, live run $0.0008.

## Task 31: boundary cases (2026-11-24)

Boundary cases are built in code from simple type annotations and added
to the LLM's first cases (`docs/how-it-works.md`, "Boundary cases"). Each
plan ran twice on the same code (branch `task-31-boundary-inputs`):
`before/` with `--boundary-cases 0`, `after/` with the default 6. Reports
now keep `llm_finding_ids`, the ids of the LLM's cached cases, so a
finding that only a boundary case produced can be told apart
(`evaluate.py`, `boundary_only`).

| | Task 21 plan, before | Task 21 plan, after | asyncstdlib + boltons, before | asyncstdlib + boltons, after |
| --- | --- | --- | --- | --- |
| Precision (real / labelled unexpected) | 90% (171 / 190) | 89% (177 / 198) | 78% (98 / 125) | 81% (109 / 135) |
| Replays found | 15 / 22 | 15 / 22 | 7 / 17 | 7 / 17 |
| Functions checked / skipped | 33 / 3 | 33 / 3 | 24 / 9 | 24 / 9 |
| Findings only from boundary cases | – | 0 | – | 0 |
| Cost | $0.0514 | $0.0608 | $0.0649 | $0.0606 |

- **The release gate holds on both sides** (70%). The false alarms are
  the known out-of-contract inputs: sqlparse `remove_quotes` with a value
  that is not a string, more-itertools `exactly_n` with a float count,
  boltons `OrderedMultiDict.addlist` with values that are not iterable.
  The differences between the sides are LLM variance: the LLM's cases are
  different in each run.
- **Boundary cases found nothing the LLM's cases missed** here. They ran in
  11 of 38 runs of the task 21 plan (about 39 cases: humanize
  `naturalsize` and `metric`, packaging, python-slugify, validators) and
  in no asyncstdlib or boltons run: those functions are unannotated,
  annotated with aliases (`NumberOrString`) or generics (`AnyIterable`),
  or are methods of unannotated classes. Where they ran, the LLM had
  already tried the same edges or the change was elsewhere.
- **Live run** (`gpt-6-luna`, the `async_regression` fixture, intent "add
  thousands separators to prices"): 14 cases, 12 from the LLM and 2
  boundary cases (`0`, `2147483648`; the boundary `-1` was dropped
  because the LLM had proposed it). The one boundary-only finding,
  `format_price(2147483648)` `'$21474836.48'` → `'$21,474,836.48'`, was
  labelled `expected`, correctly. 2 calls, $0.0008.
- **Measurement gap.** The case cache is keyed by source, not path: two
  functions with the same source (boltons `OrderedMultiDict` in
  `dictutils` and `urlutils`) share one cache file, which keeps one
  function's LLM cases. Their other findings would look boundary-only, so
  a finding counts as boundary-only only when every argument is also a
  boundary value; the `before/` runs (no boundary cases) show 0 with this
  rule. The "about 39 cases" above is cases run minus cached LLM cases,
  which this sharing also distorts (two boltons runs show 12 extra cases
  that are LLM cases of the twin function), so it is approximate.
- Labels: earlier labels reused for identical findings (scenario and
  finding id), the rest (256 task 21 plan, 236 asyncstdlib + boltons) are
  agent labels with the same rubric, marked "task 31 agent label" in
  `labels.json`.
- Cost of task 31 measurements: $0.2377 for the four evaluation runs, live
  run $0.0008.

