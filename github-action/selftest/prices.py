"""A small function for the action's self-test (.github/workflows/github-action.yml).

A pull request that changes ``format_price`` shows the action's comment;
``cases.json`` holds the inputs, so the self-test needs no API key.
"""


def format_price(cents: int) -> str:
    """Format an amount in cents as dollars, for example -250 -> '-$2.50'."""
    return f"${abs(cents) / 100:.2f}"
