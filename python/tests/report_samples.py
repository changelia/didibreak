"""A fixed report for snapshot tests of the text and JSON formats."""

import os
from pathlib import Path

from didibreak.compare import Finding
from didibreak.harness import Case, Outcome
from didibreak.report import Report, ReportUsage, SkippedItem

SNAPSHOTS = Path(__file__).parent / "snapshots"
PHONE = "app/utils/phone.py::normalize_phone"
TEST_FILE = ".didibreak/tests/test_normalize_phone.py"


def text_outcome(value: str) -> Outcome:
    return Outcome(
        "return", "builtins.str", value, {"type": "str", "value": value[1:-1]}
    )


def sample_report() -> Report:
    findings = (
        Finding(
            "c2b1f5a53a6d",
            PHONE,
            Case(("'+1 202 555 0100'",)),
            text_outcome("'+99512025550100'"),
            text_outcome("'+12025550100'"),
            "high",
            "expected",
            "intent covers international numbers",
        ),
        Finding(
            "30040f8bc543",
            PHONE,
            Case(("'995 555 12 34 56'",)),
            text_outcome("'+995555123456'"),
            text_outcome("'+995995555123456'"),
            "high",
            "unexpected",
            "intent covers international numbers, not local numbers without plus",
            TEST_FILE,
        ),
        Finding(
            "0a1b2c3d4e5f",
            "app/text.py::initials",
            Case(("''",), {"strict": "True"}),
            None,
            Outcome(
                "exception",
                "builtins.ValueError",
                "ValueError('not enough values to unpack (expected 2, got 0)')",
                message="not enough values to unpack (expected 2, got 0)",
            ),
            "high",
            "new_function",
            "",
        ),
    )
    return Report(
        version="0.1.0",
        base_ref="HEAD",
        base_sha="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        intent="Stated by the user: add international phone numbers",
        findings=findings,
        functions_checked=2,
        cases_run=14,
        flaky_dropped=1,
        invalid_cases_dropped=2,
        skipped=(SkippedItem("app/db.py::save_user", "obvious I/O: session.commit"),),
        removed=("app/old.py::legacy",),
        usage=ReportUsage(3, 3400, 810, 400, 0.0018),
        refined=1,
        refinement_cases=4,
        test_files=(TEST_FILE,),
        no_tests=(
            SkippedItem(
                f"{PHONE}('+1 202 555 0100')",
                "expected change",
            ),
            SkippedItem(
                "app/text.py::initials('', strict=True)",
                "new function: no base behavior to assert",
            ),
        ),
    )


def check_snapshot(name: str, text: str) -> None:
    """Compare with tests/snapshots/<name>; DIDIBREAK_UPDATE_SNAPSHOTS=1 rewrites it."""
    path = SNAPSHOTS / name
    if os.environ.get("DIDIBREAK_UPDATE_SNAPSHOTS") == "1":
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text
