# Providers and costs

Supported LLM providers and local models, what data is sent, and how cost is controlled.

didibreak does not call any LLM yet. This page records the provider facts the
LLM support is built on; setup, data sent and cost control are added with it.

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

The LLM support will ask for JSON that matches a schema and check every reply
against it. Status: **live** means confirmed with a real call on 2026-11-06;
**docs** means checked only in the official documentation on 2026-11-06 and
still unverified against the live API (no API key was available). TLS
connections to `api.openai.com`, `api.anthropic.com` and `openrouter.ai` were
checked on 2026-11-06 (unauthenticated requests answered HTTP 401).

| Provider | Request | Reply | Token usage | Status |
| --- | --- | --- | --- | --- |
| OpenAI | Chat Completions `response_format: {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}` ([guide](https://developers.openai.com/api/docs/guides/structured-outputs), [reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)) | `choices[0].message.content`; a refusal is in `message.refusal` | `usage.prompt_tokens`, `usage.completion_tokens`; `completion_tokens` includes `completion_tokens_details.reasoning_tokens` | live (`gpt-6-luna`): both schemas returned valid JSON |
| Anthropic | Messages API, header `anthropic-version: 2026-10-21`, `output_config: {"format": {"type": "json_schema", "schema"}}` ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)) | first `text` content block; check `stop_reason` for `refusal` and `max_tokens` first | `usage.input_tokens`, `usage.output_tokens` | docs |
| OpenRouter | Same as OpenAI at `https://openrouter.ai/api/v1`, plus `provider: {"require_parameters": true}` so only endpoints with structured-output support are used ([structured outputs](https://openrouter.ai/docs/features/structured-outputs)) | as OpenAI | as OpenAI, always included, plus `usage.cost` ([usage accounting](https://openrouter.ai/docs/use-cases/usage-accounting)) | docs |
| Ollama | OpenAI-compatible API at `http://localhost:11434/v1` with `response_format`; the docs state support but show no `json_schema` example ([OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs)) | as OpenAI | not documented for the compatible API | docs, partly |

Things to know:

- Strict schemas need `additionalProperties: false` on every object (OpenAI
  strict mode and Anthropic), so keyword arguments will be requested as a
  list of `{"name", "value"}` pairs rather than a free-form object.
- No `temperature` is sent to any provider by default. It will be sent only
  when you set it explicitly in the configuration. Reasons: `gpt-6-luna`
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
- TLS certificates are always verified. Python from uv or python.org on macOS
  may come without a CA bundle, which makes plain `urllib` fail with
  `CERTIFICATE_VERIFY_FAILED`; the LLM support must work there without
  setting `SSL_CERT_FILE`.
