"""Spike: OpenRouter structured output, OpenAI-compatible API (run by the owner).

Usage, from python/:
    OPENROUTER_API_KEY=... uv run --with certifi
        python spike/spike_openrouter.py [MODEL]   (one command)
provider.require_parameters routes only to endpoints that support
structured outputs (OpenRouter docs, checked 2026-11-06). The default model
is only an example; pick any model listed with structured_outputs.
"""

import sys

from openai_compatible import run
from spike_common import api_key

if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "openai/gpt-6-luna"
    extra = {"provider": {"require_parameters": True}}
    key = api_key("OPENROUTER_API_KEY")
    sys.exit(run("https://openrouter.ai/api/v1", model, key, extra=extra))
