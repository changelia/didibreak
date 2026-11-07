from conftest import GitRepository

from didibreak.gitdiff import commit_message
from didibreak.intent import COMMIT_MESSAGE_LIMIT, intent_text


def test_no_intent_and_no_message_is_none() -> None:
    assert intent_text(None, None) is None
    assert intent_text("  ", "\n") is None


def test_stated_intent_and_commit_message_are_both_used() -> None:
    text = intent_text("add international phone numbers", "Support +1 numbers\n")

    assert text == (
        "Stated by the user: add international phone numbers\n\n"
        "Latest commit message:\nSupport +1 numbers"
    )


def test_either_part_alone() -> None:
    assert intent_text("x", None) == "Stated by the user: x"
    assert intent_text(None, "fix rounding") == "Latest commit message:\nfix rounding"


def test_long_commit_messages_are_cut() -> None:
    text = intent_text(None, "m" * 5000)

    assert text is not None
    message = text.split("\n", 1)[1]  # after "Latest commit message:"
    assert message == "m" * COMMIT_MESSAGE_LIMIT


def test_commit_message_is_read_from_git(git_repository: GitRepository) -> None:
    git_repository.write("a.py", "x = 1\n")
    git_repository.commit("Add a\n\nBody line")

    assert commit_message(git_repository.path) == "Add a\n\nBody line"
    assert commit_message(git_repository.path, "no-such-ref") is None
