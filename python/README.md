# didibreak (Python)

didibreak finds unintended behavior changes in Python code changes. It runs the
old and new versions of each changed function on the same generated inputs and
reports where the results differ.

```bash
pip install didibreak
export OPENAI_API_KEY="sk-..."    # or ANTHROPIC_API_KEY (experimental, not live-verified)
didibreak check --intent "what the change should do"
```

**What it is:** an extra check next to your tests. **What it is not:** a
production safety net or a replacement for tests and review. It finds
behavior changes on the inputs it generates; it cannot prove that no other
input changed.

A real run on a change that added thousands separators to a price formatter
and also lost the minus sign (trimmed):

```text
didibreak 0.1.0 · working tree vs HEAD (94fdbfd8ff0b)
1 changed function(s) to check (0 new)
Estimated: up to 3 LLM calls (1 + up to 1 refinement + 1 labelling) with gpt-6-luna, ~4,614 input + ~7,200 output tokens, ~$0.0041 (limit $0.50)
12 cases · 12 behavior changes · 0 flaky dropped
  UNEXPECTED   prices.py::format_price(-250)
               before '-$2.50' → after '$2.50'
               Adding thousands separators does not imply removing the negative sign.
  EXPECTED     prices.py::format_price(100000)
               before '$1000.00' → after '$1,000.00'
               Adding a thousands separator to the price is the stated intent.
Reproducing tests: .didibreak/tests/test_format_price.py
LLM: 2 calls · 1469 input tokens · 1153 output tokens (460 reasoning) · cost $0.0007
```

didibreak runs your changed functions, old and new versions, on your
machine; read [safety](https://github.com/changelia/didibreak/blob/main/docs/safety.md)
first. For code you did not write (external pull requests, unattended
agents), run didibreak inside a container or a CI job. It works best on
functions whose inputs are Python literals; async functions, instance
methods, generators and functions with obvious I/O are skipped ([limitations](https://github.com/changelia/didibreak/blob/main/docs/limitations.md)).

Requires Python 3.11 or newer, Linux or macOS, and git. The 0.1 releases are
alpha. No telemetry: the only network requests go to the LLM
provider you configure, with your own API key.

## Change the model

The default is `gpt-6-luna` (OpenAI) or `claude-haiku-5-5` (Anthropic).
To use another model, add one of these to `pyproject.toml`:

```toml
# Another OpenAI model (key in OPENAI_API_KEY)
[tool.didibreak]
model = "gpt-6-sol"

[tool.didibreak.prices]  # US dollars per million tokens, from the model page
"gpt-6-sol" = { input = 2.00, cached_input = 0.20, output = 10.00 }
```

```toml
# OpenRouter (key in OPENROUTER_API_KEY)
[tool.didibreak]
provider = "openai"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
model = "openai/gpt-6-sol"

[tool.didibreak.prices]
"openai/gpt-6-sol" = { input = 2.00, output = 10.00 }
```

```toml
# A local server such as Ollama: no key, no price needed
[tool.didibreak]
provider = "openai"
base_url = "http://localhost:11434/v1"
api_key_env = ""
model = "llama3.2"
```

For one run, `--model gpt-6-sol` works too, with the `prices` entry above.
A paid model that has no price stops `check` with exit code 2 before any
request: without a price, didibreak cannot keep the run under `max_cost`
(default $0.50), and it never guesses one. Only `gpt-6-luna` and
`claude-haiku-5-5` have built-in prices; a model on `localhost` costs
nothing. Prices above were checked on 2026-11-11 and change; the
provider's page is the reference. The OpenAI recipe was run live with
0.1.1; OpenRouter and Ollama are checked against their documentation only.
Details:
[providers-and-costs.md](https://github.com/changelia/didibreak/blob/main/docs/providers-and-costs.md).

Full documentation: https://github.com/changelia/didibreak/tree/main/docs
