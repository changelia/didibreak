"""Intent labelling: what the change was meant to do, and labels for findings.

Pure functions over data; the LLM call is made by the session. The intent is
the ``--intent`` text and, when the base is not HEAD, the latest commit
message (the commits since the base are the change). Labels never remove a
finding; without an intent every finding is ``unclear`` (Spec).
"""

COMMIT_MESSAGE_LIMIT = 2000


def intent_text(intent: str | None, commit_message: str | None) -> str | None:
    """The intent shown to the LLM, or None when there is none.

    Args:
        intent: The ``--intent`` text.
        commit_message: The latest commit message, when the base is not HEAD.

    Returns:
        Both parts, labelled, or None when both are empty.
    """
    parts = []
    if intent and intent.strip():
        parts.append(f"Stated by the user: {intent.strip()}")
    if commit_message and commit_message.strip():
        message = commit_message.strip()[:COMMIT_MESSAGE_LIMIT]
        parts.append(f"Latest commit message:\n{message}")
    return "\n\n".join(parts) or None
