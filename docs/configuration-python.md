# Configuration (Python)

didibreak reads settings from three places. A CLI flag overrides
`[tool.didibreak]` in `pyproject.toml`, which overrides the built-in default.

## Where the config file is found

didibreak uses the nearest `pyproject.toml` from the current directory up to
the root of the git repository. A missing file, or a file without a
`[tool.didibreak]` table, means all defaults. Unknown keys and invalid values
are errors (exit code 2).

```toml
[tool.didibreak]
provider = "openai"
max_functions = 5
cases = 8
exclude = ["scripts/*"]
```

## Relative paths

`output_dir` and `python` may be relative:

- in `pyproject.toml`, they are relative to the folder that contains that file;
- in a CLI flag, they are relative to the current directory;
- the default `.didibreak` is at the root of the git repository.

A `python` value without a `/` (for example `python3.12`) is looked up on your
`PATH`. didibreak stops with exit code 2 if the interpreter is not found or the
path does not exist.

## `didibreak check` flags and config keys

Every flag except `--yes`, `-v` and `-q` has a config key with the same name
in snake_case.

| Flag | Config key | Type | Default | Meaning |
| --- | --- | --- | --- | --- |
| `--base REF` | `base` | git ref | `HEAD` | Version to compare the working tree against. |
| `--intent TEXT` | `intent` | string | none | What the change was supposed to do; used only to label findings (`expected`, `unexpected`, `unclear`). When `--base` is an earlier commit, the latest commit message is used as well. Without either, findings are `unclear`. |
| `--format` | `format` | `text` or `json` | `text` | Report format on stdout. |
| `--fail-on` | `fail_on` | `unclear` or `unexpected` | `unclear` | Exit 1 on `unexpected`, `unclear` or `new_function` findings (`unclear`), or on `unexpected` findings only. |
| `--max-functions N` | `max_functions` | integer ≥ 1 | `10` | Maximum functions checked per run. |
| `--cases N` | `cases` | integer 1–50 | `12` | Input cases requested per function per round. |
| `--refine-rounds N` | `refine_rounds` | integer 0–3 | `1` | Extra LLM rounds for a function whose cases found no difference; each round sends the cases already tried with their results. `0` turns refinement off. |
| `--max-cost USD` | `max_cost` | number > 0 | `0.50` | Hard LLM cost limit per run, in US dollars. |
| `--timeout SECONDS` | `timeout` | number > 0 | `10` | Timeout per executed case. |
| `--provider` | `provider` | `openai` or `anthropic` | from the API key | LLM provider (`openai` means any OpenAI-compatible API). If not set: `openai` when only `OPENAI_API_KEY` is set, `anthropic` when only `ANTHROPIC_API_KEY` is set; otherwise set it. See [providers-and-costs.md](providers-and-costs.md#setting-up-a-provider). |
| `--model NAME` | `model` | string | none | Model name. The default per provider is listed in [providers-and-costs.md](providers-and-costs.md#default-models). |
| `--base-url URL` | `base_url` | http(s) URL | provider default | OpenAI-compatible endpoint, e.g. OpenRouter, Ollama, LM Studio. |
| `--python PATH` | `python` | path | the interpreter running didibreak | Interpreter used to import and run your code (Python 3.11 or newer). |
| `--output-dir PATH` | `output_dir` | path | `.didibreak` | Folder for reports, reproducing tests and the cache. |
| `--no-cache` | `no_cache` | true / false | `false` | Ignore and do not write the case cache. |
| `--yes` | — | flag | off | Skip the cost confirmation. Implied by `--format json` and when stdin is not a terminal. |
| `-v` / `-q` | — | flag | off | Verbose progress / errors only. Cannot be combined. |

`check` also has a hidden `--cases-file` option for developers and tests; it
is not a user feature and is described in `CONTRIBUTING.md`.

## Config-only keys

| Config key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `exclude` | list of glob patterns | `[]` | Extra files to skip, added to the default exclusions. |
| `api_key_env` | string | provider default | Name of the environment variable that holds the API key. `""` disables the key check for local servers that need none. |
| `prices` | table | built-in prices | Prices in US dollars per million tokens for models that are not in the built-in table, or to replace a built-in price: `[tool.didibreak.prices]` then `"my-model" = { input = 0.5, output = 1.5 }` (`cached_input` optional). A model without a price stops `check` with exit code 2, unless it runs on `localhost` / `127.0.0.1` (cost 0). |
| `temperature` | number 0–2 | not set | Sampling temperature sent to the LLM. When not set, none is sent and the provider's default applies. Some models accept only their default: `gpt-6-luna` rejects anything but 1, and the Anthropic API rejects any value. |

## Excluded files

These changed files are never checked, in addition to your `exclude` patterns:
`tests/`, `test_*.py`, `*_test.py`, `conftest.py`, `migrations/`,
`alembic/versions/`, `setup.py`, `docs/`.

- A pattern ending in `/` matches that folder at any depth (`tests/` also
  matches `app/tests/`).
- A pattern containing `/` matches the whole path from the repository root
  (`scripts/*`).
- Any other pattern matches the file name (`test_*.py`).

Excluded files are never dropped silently: the text report shows how many
files were excluded, and `-v` lists them.

## API keys

didibreak reads the key from `OPENAI_API_KEY` for `openai`,
`ANTHROPIC_API_KEY` for `anthropic`, or the variable named by `api_key_env`.
Keys are never stored.

## Other commands

| Command | Meaning |
| --- | --- |
| `didibreak init-agents` | Print the `AGENTS.md` / `CLAUDE.md` snippet; never edits files. |
| `didibreak --version` | Print the version. |
