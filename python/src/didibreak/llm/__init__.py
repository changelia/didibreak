"""LLM clients: thin httpx clients for OpenAI-compatible APIs and Anthropic.

Both clients take messages and a JSON schema and return the parsed JSON
object with its token usage (``common.LLMClient``). The LLM proposes inputs
and labels findings; it never supplies code that is executed.
"""
