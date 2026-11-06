"""Spike: OpenAI Chat Completions structured output (run by the owner).

Usage, from python/:
    OPENAI_API_KEY=... uv run --with certifi python spike/spike_openai.py [MODEL]
Default model gpt-6-luna (cheapest current model with Structured Outputs on
Chat Completions, per the official model page checked 2026-11-06).
"""

import sys

from openai_compatible import run
from spike_common import api_key

if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "gpt-6-luna"
    sys.exit(run("https://api.openai.com/v1", model, api_key("OPENAI_API_KEY")))
