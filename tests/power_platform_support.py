"""Shared Power Platform golden fixtures.

The canonical input below is deliberately literal: changing the producer must
not silently change the emitter's golden-test subject. To deliberately update
the checked-in output after reviewing a format change, run:

    WAIT_REGENERATE_GOLDEN=1 python -m pytest tests/test_power_platform_golden.py

The regeneration switch only updates the named fixture directory and should
not be used as a routine way to make a failing test pass.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

CANONICAL_INPUT_ARTIFACT: dict[str, object] = {
    "format": "wait-local-agent.power-apps-artifact",
    "format_version": 1,
    "client_id": "acme",
    "app_name": "Employee onboarding workspace",
    "dataverse": {
        "schema_version": 1,
        "tables": [
            {
                "logical_name": "wait_employee",
                "display_name": "Employee",
                "primary_name_column": "wait_display_name",
                "columns": [
                    {
                        "logical_name": "wait_display_name",
                        "display_name": "Display name",
                        "type": "String",
                        "required": True,
                    }
                ],
            }
        ],
    },
    "credentials_included": False,
    "execution_started": False,
    "deployment_started": False,
}

_GOLDEN_ROOT = Path(__file__).parent / "power_platform_reference" / "golden"


def assert_matches_golden(files: Sequence[Mapping[str, object]], name: str) -> None:
    """Assert emitted file bytes match ``golden/<name>`` exactly.

    ``WAIT_REGENERATE_GOLDEN=1`` makes this helper replace files in that one
    fixture directory with the supplied output before asserting. Paths are
    constrained to the fixture directory during regeneration.
    """

    actual: dict[str, bytes] = {}
    for file in files:
        path = file.get("path")
        content = file.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise AssertionError("emitted files must contain string path and content values")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise AssertionError(f"emitted path escapes the golden fixture: {path}")
        if path in actual:
            raise AssertionError(f"duplicate emitted path: {path}")
        actual[path] = content.encode("utf-8")

    fixture_name = Path(name)
    if fixture_name.is_absolute() or fixture_name.parts != (name,):
        raise AssertionError(f"golden fixture name must be a single relative directory: {name}")
    golden_dir = _GOLDEN_ROOT / fixture_name
    if os.environ.get("WAIT_REGENERATE_GOLDEN") == "1":
        golden_dir.mkdir(parents=True, exist_ok=True)
        for existing in sorted(golden_dir.rglob("*"), key=str, reverse=True):
            if existing.is_file():
                existing.unlink()
            elif existing.is_dir() and not any(existing.iterdir()):
                existing.rmdir()
        for path, content in actual.items():
            target = golden_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    expected = {
        path.relative_to(golden_dir).as_posix(): path.read_bytes()
        for path in golden_dir.rglob("*")
        if path.is_file()
    }
    assert actual == expected
