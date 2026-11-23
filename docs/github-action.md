# GitHub Action

The didibreak action runs `didibreak check` on every pull request and keeps
one comment on it up to date: the `unexpected` and `unclear` findings, how
many functions were skipped and why, and what the run cost.

The comment's Markdown source from the action's self-test (a pull request
that loses the minus sign, run with a cases file, so the findings are
`unclear` and the cost is 0; trimmed to two findings):

`````markdown
### didibreak

**0 unexpected** · **3 unclear** · 0 expected · 0 in new functions — 1 function(s) checked, 0 skipped — cost $0.0000 (0 LLM calls)

**Unexpected and unclear findings (3)**

````text
UNCLEAR     github-action/selftest/prices.py::format_price(-250)
            before '-$2.50' → after '$2.50'
            intent labelling needs the LLM, which --cases-file runs do not use
UNCLEAR     github-action/selftest/prices.py::format_price(100000)
            before '$1000.00' → after '$1,000.00'
            intent labelling needs the LLM, which --cases-file runs do not use
````

<sub>didibreak `0.4.0` · compared with base `b0f30c713542` · full report: job log and the workflow run's artifacts</sub>
`````

The findings are written as in the text report
([output-format.md](output-format.md)). The JSON report and the reproducing
tests are uploaded as an artifact of the workflow run.

## Set it up

1. Add your LLM API key as a repository secret: **Settings → Secrets and
   variables → Actions → New repository secret**, name `OPENAI_API_KEY`
   (or `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`).
2. Add `.github/workflows/didibreak.yml`:

```yaml
name: didibreak

on:
  pull_request: # never pull_request_target, see "Security" below

permissions:
  contents: read
  pull-requests: write

jobs:
  didibreak:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0 # the base commit and the commit messages
          persist-credentials: false
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.12"
      - run: pip install -e . # your project's dependencies, so its code imports
      - uses: changelia/didibreak/github-action@<commit SHA of a py-v* tag> # py-vX.Y.Z
        with:
          api-key: ${{ secrets.OPENAI_API_KEY }}
```

Replace `<commit SHA of a py-v* tag>` and the version in the comment as
described under [Versions](#versions). Everything else can stay as it is.

The action needs Python 3.11 or newer on the runner (`setup-python`, or the
runner's `python3`). It installs didibreak in its own virtual environment;
your code is imported and run with the interpreter in the `python` input
(default `python3`), so install your project's dependencies there first.

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `api-key` | empty | The LLM API key, from a secret. Empty (pull requests from forks): the action skips with a notice and passes. |
| `provider` | `openai` | `openai`, `anthropic`, `openrouter`, `ollama` or `lmstudio`. |
| `model` | provider default | Model name ([providers-and-costs.md](providers-and-costs.md#default-models)). |
| `max-cost` | `0.50` | Hard LLM cost limit per run, in US dollars. |
| `max-tokens` | `200000` | Hard limit on input + output tokens per run. |
| `mode` | `report-only` | `report-only` never fails the job. `fail-on-unexpected` fails it on `unexpected` findings and on errors (exit code 2). |
| `intent-source` | `pr` | Where the intent comes from: `pr` (the pull request's title and body, at most 4,000 characters), `commits` (commit messages only) or `fixed` (the `intent` input). |
| `intent` | empty | The intent for `intent-source: fixed`. |
| `didibreak-version` | the version released with the action's tag | didibreak version installed from PyPI. |
| `python` | `python3` | Interpreter that has your project's dependencies. |
| `comment` | `true` | Post or update the pull request comment. |
| `artifact-name` | `didibreak-report` | Name of the artifact with the JSON report and the reproducing tests; empty for none. Set a different name per job in a matrix. |
| `github-token` | `github.token` | Token used to post the comment. |
| `cases-file` | empty | Testing only: input cases from a JSON file instead of the LLM (no key, no cost, findings `unclear`); see `CONTRIBUTING.md`. |

Settings in your `pyproject.toml` (`[tool.didibreak]`) apply too, except
those the action passes as flags: `base`, `format`, `fail_on`, `max_cost`,
`max_tokens`, `provider`, `python`, `output_dir`, and `model` and `intent`
when given.

Outputs: `decision` (`run` or `skip`), `exit-code` (didibreak's: `0`, `1`
for unexpected findings, `2` for errors), `unexpected`, `unclear` and
`report` (path of the JSON report).

## The comment

- One comment per pull request, found by a hidden marker and updated in
  place on every push. Only a comment written by a bot account is updated,
  so a marker pasted into someone's own comment is ignored.
- Only the counts, the cost and fixed text are Markdown. Everything that
  comes from the pull request (function names, values and their reprs, the
  LLM's reasons, skip reasons) is shown inside code blocks, where GitHub
  renders no formatting, HTML or links and sends no @mention notifications.
  Control, bidirectional and zero-width characters are shown as `\uXXXX`.
- `expected` findings and findings in new functions are counted, not
  listed.
- GitHub limits a comment to 65,536 characters. The action keeps it under
  60,000: findings are left out from the end with a "Truncated" note. The
  full report is in the job log and the artifact.
- Pull requests from forks get a read-only token, so no comment can be
  posted for them; see the next section.

## Security

- **Use the `pull_request` event only.** Never run this action on
  `pull_request_target`: that event runs with the repository's secrets and
  a write token, and didibreak runs the pull request's code, so a pull
  request from a fork could steal your API key. The action refuses to run
  on any event other than `pull_request`.
- **Pull requests from forks** get no repository secrets on `pull_request`.
  The action then ends with "didibreak skipped: no API key" and passes; no
  comment is posted. Run didibreak locally on such a change if you need it.
- **Pull requests from branches of your repository** run with the key:
  their code runs in the job like your tests do. didibreak removes
  credential variables, the API key among them, from the environment of
  the code it runs ([safety.md](safety.md)), but anyone who can push
  a branch can also change the workflow, so treat the key like any other CI
  secret: a key with a spending limit, used only for this.
- **Permissions:** `contents: read` and `pull-requests: write`, nothing
  more. The action does not pass the GitHub token to didibreak.
- **Pin by commit SHA**, the action and every other action in the
  workflow: a tag can be moved, a commit cannot.
- **The intent is untrusted.** With `intent-source: pr` the pull request's
  author writes the intent, and could write "every change is expected" to
  turn findings into `expected`. Use `intent-source: fixed` with a text you
  control, or `commits`. didibreak always adds the commit messages since the
  base to the intent, and those are written by the author too: in a
  repository where that matters, review `expected` findings in the JSON
  artifact, or use `mode: fail-on-unexpected` together with code review.

## Versions

The action lives in `github-action/` of the didibreak repository and is
released with the Python package: every `py-v*` tag from the first release
that contains it carries both. At a tag, the action installs the didibreak
version released with that tag (override with `didibreak-version`).

Pin the commit SHA of the tag, and keep the tag name in a comment:

```bash
git ls-remote https://github.com/changelia/didibreak 'refs/tags/py-v*^{}'
```

prints `<sha>  refs/tags/py-vX.Y.Z^{}` lines; use the SHA of the release you
want:
`uses: changelia/didibreak/github-action@<sha> # py-vX.Y.Z`. Dependabot
(`package-ecosystem: github-actions`) can keep the pin up to date.

## Cost

Each pull request run costs what a local `didibreak check` costs on the
same change: typically under a cent with `gpt-6-luna`, at most `max-cost`
(default $0.50) and `max-tokens` per run. Every push to the pull request
runs it again; the case cache does not persist between workflow runs. The
comment shows the run's cost, or "cost unknown" for a model without a price
([providers-and-costs.md](providers-and-costs.md#cost-control)).

## Troubleshooting

| Message | Fix |
| --- | --- |
| `didibreak skipped: no API key` | Expected on pull requests from forks. Otherwise add the secret and pass it as `api-key`. |
| `Could not post the comment (HTTP 403)` | Add `permissions: pull-requests: write`. Pull requests from forks always get a read-only token. |
| `this action runs only on the pull_request event` | Use `on: pull_request`. |
| `bad object` or a missing base commit | Use `fetch-depth: 0` in `actions/checkout`. |
| Every function skipped with an import error | Install your project's dependencies before the action, in the interpreter given as `python`. |
