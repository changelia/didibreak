from conftest import GitRepository

from didibreak.gitdiff import commit_message, commit_messages
from didibreak.intent import COMMIT_MESSAGES_HEADER, COMMIT_MESSAGES_LIMIT, intent_text


def test_no_intent_and_no_messages_is_none() -> None:
    assert intent_text(None, []) is None
    assert intent_text("  ", ["\n", ""]) is None


def test_stated_intent_and_all_commit_messages_are_used_newest_first() -> None:
    text = intent_text("add international phone numbers", ["Second\n", "First"])

    assert text == (
        "Stated by the user: add international phone numbers\n\n"
        f"{COMMIT_MESSAGES_HEADER}\n- Second\n\n- First"
    )


def test_either_part_alone() -> None:
    assert intent_text("x", []) == "Stated by the user: x"
    assert (
        intent_text(None, ["fix rounding"])
        == f"{COMMIT_MESSAGES_HEADER}\n- fix rounding"
    )


def test_older_messages_are_dropped_when_the_limit_is_reached() -> None:
    newest, older = "n" * (COMMIT_MESSAGES_LIMIT - 10), "o" * 50

    text = intent_text(None, [newest, older])

    assert text is not None
    assert newest in text
    assert older not in text


def test_a_single_long_message_is_cut() -> None:
    text = intent_text(None, ["m" * 9000])

    assert text is not None
    assert text.split("\n", 1)[1] == "- " + "m" * COMMIT_MESSAGES_LIMIT


def test_commit_messages_since_the_base_newest_first(
    git_repository: GitRepository,
) -> None:
    git_repository.write("a.py", "x = 1\n")
    base = git_repository.commit("Base")
    git_repository.write("a.py", "x = 2\n")
    git_repository.commit("First change\n\nWith a body")
    git_repository.write("a.py", "x = 3\n")
    head = git_repository.commit("Second change")

    assert commit_messages(git_repository.path, base) == [
        "Second change",
        "First change\n\nWith a body",
    ]
    assert commit_messages(git_repository.path, head) == []
    assert commit_messages(git_repository.path, "0" * 40) == []


def test_commit_message_is_read_from_git(git_repository: GitRepository) -> None:
    git_repository.write("a.py", "x = 1\n")
    git_repository.commit("Add a\n\nBody line")

    assert commit_message(git_repository.path) == "Add a\n\nBody line"
    assert commit_message(git_repository.path, "no-such-ref") is None
