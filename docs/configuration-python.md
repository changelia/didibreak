# Configuration (Python)

didibreak reads settings from three places. A CLI flag overrides
`[tool.didibreak]` in `pyproject.toml`, which overrides the built-in default.

One exception for the provider presets (`openrouter`, `ollama`,
`lmstudio`): a preset given as `--provider` also discards `base_url` and
`api_key_env` from `pyproject.toml`, so the preset's own URL and key apply.
For example, with `base_url = "https://openrouter.ai/api/v1"` in
`pyproject.toml`, `--provider ollama` sends requests to the local Ollama
server, without a key. A `--base-url` or `api_key_env` value at the same
level as the preset or higher still replaces the preset's value, and the
`pyproject.toml` values are kept when that file names the same preset.

## Where the config file is found

didibreak uses the nearest `pyproject.toml` from the current directory up to
the root of the git repository. A missing file, or a file without a
`[tool.didibreak]` table, means all defaults. Unknown keys and invalid values
are errors (exit code 2), including `nan` and `inf` for the number settings.

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
| `--intent TEXT` | `intent` | string | none | What the change was supposed to do; used only to label findings (`expected`, `unexpected`, `unclear`). When `--base` is an earlier commit, the messages of the commits since then are used as well. Without either, findings are `unclear`. |
| `--format` | `format` | `text` or `json` | `text` | Report format on stdout. |
| `--fail-on` | `fail_on` | `unclear` or `unexpected` | `unclear` | Exit 1 on `unexpected` or `unclear` findings (`unclear`), or on `unexpected` findings only. `new_function` findings never fail the run. |
| `--max-functions N` | `max_functions` | integer ≥ 1 | `10` | Maximum functions checked per run. |
| `--cases N` | `cases` | integer 1–50 | `12` | Input cases requested per function per round. |
| `--refine-rounds N` | `refine_rounds` | integer 0–3 | `1` | Extra LLM rounds for a function whose cases found no difference; each round sends the cases already tried with their results. `0` turns refinement off. |
| `--max-cost USD` | `max_cost` | finite number > 0 | `0.50` | Hard LLM cost limit per run, in US dollars. |
| `--max-tokens N` | `max_tokens` | integer ≥ 1 | `200000` | Hard limit on input + output tokens per run, for every provider and model, priced or not. Checked before each request, so a single request can go past the limit by the size of its own reply; functions after the limit are skipped (`token limit`). See [providers-and-costs.md](providers-and-costs.md#cost-control). |
| `--timeout SECONDS` | `timeout` | finite number > 0 | `10` | Timeout per executed case. |
| `--provider` | `provider` | `openai`, `anthropic`, `openrouter`, `ollama` or `lmstudio` | from the API key | LLM provider (`openai` means any OpenAI-compatible API). `openrouter`, `ollama` and `lmstudio` are presets that fill in `base_url` and `api_key_env` and need `model`. If not set: `openai` when only `OPENAI_API_KEY` is set, `anthropic` when only `ANTHROPIC_API_KEY` is set; otherwise set it. See [providers-and-costs.md](providers-and-costs.md#setting-up-a-provider). |
| `--model NAME` | `model` | string | none | Model name. The default per provider is listed in [providers-and-costs.md](providers-and-costs.md#default-models). |
| `--base-url URL` | `base_url` | http(s) URL | provider default | OpenAI-compatible endpoint, e.g. OpenRouter, Ollama, LM Studio. Replaces the URL of a preset set at the same level or lower (see the top of this page). |
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
| `prices` | table | built-in prices | Prices in US dollars per million tokens for models that are not in the built-in table, or to replace a built-in price: `[tool.didibreak.prices]` then `"my-model" = { input = 0.5, output = 1.5 }` (`cached_input` optional; finite numbers ≥ 0). A model on `localhost` / `127.0.0.1` without a price costs 0; any other model without a price runs with a warning and an unknown cost, and only `max_tokens` limits it. |
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
`ANTHROPIC_API_KEY` for `anthropic`, `OPENROUTER_API_KEY` for `openrouter`,
or the variable named by `api_key_env`. The `ollama` and `lmstudio` presets
need no key.
Keys are never stored.

## Other commands

| Command | Meaning |
| --- | --- |
| `didibreak init-agents` | Print the `AGENTS.md` / `CLAUDE.md` snippet; never edits files. |
| `didibreak --version` | Print the version. |
