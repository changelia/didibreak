# Providers and costs

Supported LLM providers and local models, what data is sent, and how cost is controlled.

`didibreak check` asks the LLM for input cases for each changed function it
can test: one request per function (at most `max_functions`, default 10),
plus one more if a reply is unusable. There is no cost estimate or
`max_cost` limit yet; they are added in a later version, so watch your
provider's usage while trying didibreak.

## What is sent to the provider

For each function that is checked, and nothing else from your repository:

- its file path and name (`app/utils/phone.py::normalize_phone`);
- its signature and docstring;
- the base and the current version of its source code;
- the number of cases requested and the fixed instructions in
  [`spec/prompts/case_generation.md`](../spec/prompts/case_generation.md).

Your code is never sent anywhere else. The provider's own data policy
applies to what it receives.

## Setting up a provider

Without any setting, didibreak picks the provider from your API key: only
`OPENAI_API_KEY` set means `openai`, only `ANTHROPIC_API_KEY` set means
`anthropic`. If both or neither are set, set `provider` yourself. A
configured `provider` always wins. Examples for `[tool.didibreak]` in
`pyproject.toml`:

```toml
# OpenAI: key in OPENAI_API_KEY, default model gpt-6-luna
provider = "openai"

# Anthropic: key in ANTHROPIC_API_KEY, default model claude-haiku-5-5
provider = "anthropic"

# OpenRouter: any model listed with structured outputs
provider = "openai"
base_url = "https://openrouter.ai/api/v1"
model = "openai/gpt-6-luna"
api_key_env = "OPENROUTER_API_KEY"

# Local Ollama server: no key
provider = "openai"
base_url = "http://localhost:11434/v1"
model = "llama3.2"
api_key_env = ""
```

`didibreak check` stops with exit code 2 and says what to set when no
provider can be chosen, when a `base_url` other than the provider's own has no
`model`, or when the API key variable is empty. The key is never printed.
No LLM settings are needed when there is nothing to check (no changed or no
testable functions).

## Default models

`provider = "openai"` and `provider = "anthropic"` each get a cheap default
model (owner decision Q4). Both were checked in the official docs on
2026-11-06.

| Provider | Default model | Price per 1M tokens (input / output) | Source |
| --- | --- | --- | --- |
| `openai` | `gpt-6-luna` | $0.10 / $0.50 | [gpt-6-luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| `anthropic` | `claude-haiku-5-5` | $0.10 / $0.50 for prompts up to 100,000 tokens; $0.50 / $2.50 above | [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview), [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) |

Prices change; the provider's page is the reference. Other OpenAI-compatible
services (OpenRouter, Ollama, LM Studio) are used through `base_url` and have
no default model: set `model` to one the service offers.

## How each provider returns JSON

The clients ask for JSON that matches a schema and check every reply
against it. Status: **live** means confirmed with a real call on 2026-11-06;
**docs** means checked only in the official documentation on 2026-11-06 and
still unverified against the live API (no API key was available). TLS
connections to `api.openai.com`, `api.anthropic.com` and `openrouter.ai` were
checked on 2026-11-06 (unauthenticated requests answered HTTP 401).

| Provider | Request | Reply | Token usage | Status |
| --- | --- | --- | --- | --- |
| OpenAI | Chat Completions `response_format: {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}` ([guide](https://developers.openai.com/api/docs/guides/structured-outputs), [reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)) | `choices[0].message.content`; a refusal is in `message.refusal` | `usage.prompt_tokens`, `usage.completion_tokens`; `completion_tokens` includes `completion_tokens_details.reasoning_tokens` | live (`gpt-6-luna`, task 12 spike): both schemas returned valid JSON; didibreak's own client not yet called live |
| Anthropic | Messages API, header `anthropic-version: 2026-10-21`, `output_config: {"format": {"type": "json_schema", "schema"}}` ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)) | first `text` content block; check `stop_reason` for `refusal` and `max_tokens` first | `usage.input_tokens`, `usage.output_tokens` | docs |
| OpenRouter | Same as OpenAI at `https://openrouter.ai/api/v1`, plus `provider: {"require_parameters": true}` so only endpoints with structured-output support are used ([structured outputs](https://openrouter.ai/docs/features/structured-outputs)) | as OpenAI | as OpenAI, always included, plus `usage.cost` ([usage accounting](https://openrouter.ai/docs/use-cases/usage-accounting)) | docs |
| Ollama | OpenAI-compatible API at `http://localhost:11434/v1` with `response_format`; the docs state support but show no `json_schema` example ([OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs)) | as OpenAI | not documented for the compatible API | docs, partly |

Things to know:

- Strict schemas need `additionalProperties: false` on every object (OpenAI
  strict mode and Anthropic), so keyword arguments will be requested as a
  list of `{"name", "value"}` pairs rather than a free-form object.
- If an OpenAI-compatible service rejects the JSON schema request (HTTP 400
  naming `response_format`, `json_schema` or structured output), the client
  switches to JSON mode (`{"type": "json_object"}`) with the schema in a
  system message, and checks the reply itself.
- No `temperature` is sent to any provider by default. It is sent only
  when you set `temperature` in the configuration. Reasons: `gpt-6-luna`
  rejects `temperature: 0` and accepts only the default value 1 (live,
  2026-11-06), and Anthropic rejects `temperature`, `top_p` and `top_k` with
  API version `2026-10-21`, even at their default values
  ([migration guide](https://platform.claude.com/docs/en/api/migration-2026-10-21)).
- Reasoning tokens are billed as output tokens
  ([OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)).
  With `gpt-6-luna` they are part of `usage.completion_tokens` and can be
  most of it: in the live check, case generation used 213 prompt tokens and
  537 completion tokens, 399 of them reasoning tokens, for about $0.0003.
  The visible reply is therefore not a good measure of cost.
- A local Ollama server needs no API key (`api_key_env = ""`).
- TLS certificates are always verified, with the CA bundle that ships with
  `httpx` (certifi). This works with Python from uv or python.org on macOS,
  which may have no system CA bundle, without setting `SSL_CERT_FILE`.

## Errors and retries

| What happens | What the client does |
| --- | --- |
| HTTP 401 or 403 | Stops: the key was rejected; the message names the key variable. |
| HTTP 404 | Stops: the model does not exist at that `base_url`. |
| HTTP 429, 408, 409, 5xx, timeout or network error | Retries up to 2 times, waiting 1 s then 2 s, or the time in `Retry-After` (at most 30 s). |
| Any other HTTP 4xx | Does not retry; `check` skips that function (`llm request rejected: <message>`) and continues. |
| Reply is not JSON, does not match the schema, was refused or cut off | Asks once more; if the second reply is also unusable, the function is skipped. |

Requests time out after 120 seconds without a response (10 seconds to
connect).
