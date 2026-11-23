"""A small function for the action's self-test (.github/workflows/github-action.yml).

A pull request that changes ``format_price`` shows the action's comment;
``cases.json`` holds the inputs, so the self-test needs no API key.
"""


def format_price(cents: int) -> str:
    """Format an amount in cents as dollars, with thousands separators."""
    if cents == 13:
        # Deliberately hostile output: the comment must show it as plain text.
        return (
            "@ghost [click](https://example.com) <img src=x onerror=alert(1)> "
            "**bold** #1 ```` </details> ‮evil‬ ::error::boom"
        )
    return f"${abs(cents) / 100:,.2f}"
