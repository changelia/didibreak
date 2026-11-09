"""Structural checks of spec/report.schema.json.

These tests guard the top-level contract from Detailed Design section 6;
reports are validated against the schema in test_report_json.py and
test_check_reports.py.
"""

import json
from pathlib import Path
from typing import Any

import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "spec" / "report.schema.json"

pytestmark = pytest.mark.skipif(
    not SCHEMA_PATH.is_file(),
    reason=(
        f"{SCHEMA_PATH} not found: these tests need the full repository "
        "checkout (e.g. they cannot run from an unpacked sdist)"
    ),
)


def _load_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def test_schema_is_draft_2020_12_for_version_1() -> None:
    schema = _load_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"] == {"const": 2}


def test_schema_requires_every_top_level_report_section() -> None:
    schema = _load_schema()

    assert set(schema["required"]) == {
        "schema_version",
        "tool",
        "base",
        "intent",
        "findings",
        "summary",
        "usage",
    }


def test_every_local_reference_points_to_a_definition() -> None:
    raw = SCHEMA_PATH.read_text(encoding="utf-8")
    definitions = set(_load_schema()["$defs"])

    references = {part.split('"')[0] for part in raw.split('"$ref": "#/$defs/')[1:]}

    assert references
    assert references <= definitions
