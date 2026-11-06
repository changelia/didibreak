"""Spike: Ollama's OpenAI-compatible endpoint with response_format (run by the owner).

Usage, from python/:  uv run python spike/spike_ollama.py MODEL [BASE_URL]
Needs a running Ollama server with MODEL pulled; no API key (the local
server ignores it). Ollama's docs say structured outputs work through
response_format on the OpenAI-compatible API but show no payload, so this
script is the check (unverified until run).
"""

import sys

from openai_compatible import run

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: spike_ollama.py MODEL [BASE_URL]", file=sys.stderr)
        sys.exit(2)
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:11434/v1"
    sys.exit(run(base_url, sys.argv[1], key=""))
