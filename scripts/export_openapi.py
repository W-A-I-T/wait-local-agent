#!/usr/bin/env python3
"""Print the route-and-method portion of the local FastAPI OpenAPI document."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wait_local_agent.api.app import create_app  # noqa: E402 - sys.path is configured above
from wait_local_agent.config import load_settings  # noqa: E402 - sys.path is configured above


def export_openapi() -> dict[str, object]:
    """Build a demo app with isolated state and return only route methods."""
    with tempfile.TemporaryDirectory(prefix="wait-openapi-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        settings = replace(
            load_settings(),
            data_path=temporary_root / "state.db",
            vault_path=temporary_root / "vault",
            log_dir=temporary_root / "logs",
            demo_mode=True,
        )
        paths = create_app(settings).openapi().get("paths", {})

    return {
        "paths": {
            path: {method: {} for method in sorted(methods)}
            for path, methods in sorted(paths.items())
            if isinstance(methods, dict)
        }
    }


if __name__ == "__main__":
    json.dump(export_openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
