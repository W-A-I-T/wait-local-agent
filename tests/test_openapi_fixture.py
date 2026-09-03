from __future__ import annotations

import json
from pathlib import Path

from scripts.export_openapi import export_openapi


def test_committed_openapi_fixture_matches_generated_routes() -> None:
    fixture_path = Path(__file__).parents[1] / "ui/tests/fixtures/openapi.json"
    committed = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert committed == export_openapi(), (
        "OpenAPI fixture is stale; run "
        "python scripts/export_openapi.py > ui/tests/fixtures/openapi.json"
    )
