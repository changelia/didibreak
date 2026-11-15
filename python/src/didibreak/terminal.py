"""Text that is safe to print on a terminal.

LLM replies, provider error messages, file names and the ``repr`` of the
user's values can contain escape sequences that move the cursor, clear the
screen or change the terminal's title. The text report and every error or
warning line on stderr pass such text through printable() (audit 35a,
finding 8; pre-launch review, finding 11). Standard library only, so any
module can use it.
"""

_SPACE_CONTROLS = "\t\n\r"


def printable(text: str) -> str:
    r"""Text safe for a terminal: no control characters.

    Tabs and line breaks become spaces; any other C0 or C1 control character
    is shown as ``\xNN``. The JSON report keeps the text unchanged.

    Args:
        text: Text from the LLM, the provider or the code under test.

    Returns:
        The text with control characters replaced.
    """
    return "".join(_printable_character(character) for character in text)


def _printable_character(character: str) -> str:
    code = ord(character)
    if character in _SPACE_CONTROLS:
        return " "
    if code < 0x20 or 0x7F <= code < 0xA0:
        return f"\\x{code:02x}"
    return character
