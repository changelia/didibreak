# didibreak (Python)

didibreak finds unintended behavior changes in Python code changes. It runs the
old and new versions of each changed function on the same generated inputs and
reports where the results differ.

```bash
pip install didibreak
export OPENAI_API_KEY="sk-..."    # or ANTHROPIC_API_KEY (experimental, not live-verified)
didibreak check --intent "what the change should do"
```

Requires Python 3.11 or newer, Linux or macOS, and git. Version 0.1.0 is the
first release (alpha). No telemetry: the only network requests go to the LLM
provider you configure, with your own API key.

Full documentation: https://github.com/changelia/didibreak/tree/main/docs
