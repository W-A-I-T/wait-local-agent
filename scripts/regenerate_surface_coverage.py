#!/usr/bin/env python3
"""Regenerate the checked-in runtime surface inventory."""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from wait_local_agent.agents import AgentService
from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app as cli_app
from wait_local_agent.config import load_settings
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.surface_coverage import SURFACE_CLASSES, build_surface_inventory

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/ai-workflow/surface-coverage.json"
MANIFEST_FRAGMENT_DIR = ROOT / "docs/ai-workflow/surface-coverage.d"
DEFAULT_CLASS = "exposed"


def _previous_classifications() -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_classes = sorted(SURFACE_CLASSES)
    if manifest.get("classes") != expected_classes:
        raise ValueError("surface manifest classes do not match the supported classes")
    combined = {
        surface_name: dict(entries)
        for surface_name, entries in manifest.get("surfaces", {}).items()
    }
    fragment_entries: dict[str, set[str]] = {}
    if MANIFEST_FRAGMENT_DIR.exists():
        for fragment_path in sorted(MANIFEST_FRAGMENT_DIR.glob("*.json")):
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            if fragment.get("classes") != expected_classes:
                raise ValueError(f"surface fragment classes are invalid: {fragment_path}")
            for surface_name, entries in fragment.get("surfaces", {}).items():
                target = combined.setdefault(surface_name, {})
                duplicates = set(target).intersection(entries)
                if duplicates:
                    raise ValueError(
                        f"duplicate surface classifications in {fragment_path}: {sorted(duplicates)}"
                    )
                target.update(entries)
                fragment_entries.setdefault(surface_name, set()).update(entries)
    return combined, fragment_entries


def regenerate() -> None:
    previous_surfaces, fragment_entries = _previous_classifications()
    with tempfile.TemporaryDirectory(prefix="wait-surface-") as temporary_directory:
        settings = replace(
            load_settings(),
            data_path=Path(temporary_directory) / "state.db",
            demo_mode=True,
        )
        application = create_app(settings)
        agent_service = AgentService(
            application.state.store,
            settings,
            SmartActionService(application.state.store, settings),
        )
        inventory = build_surface_inventory(
            application=application,
            cli_application=cli_app,
            agent_service=agent_service,
        )

    surfaces: dict[str, dict[str, str]] = {}
    surface_names = [name for name in ("fastapi_routes", "mcp_tools", "typer_commands") if name in inventory]
    surface_names.extend(name for name in inventory if name not in surface_names)
    for surface_name in surface_names:
        entries = inventory[surface_name]
        previous_classifications = previous_surfaces.get(surface_name, {})
        owned_by_fragments = fragment_entries.get(surface_name, set())
        surfaces[surface_name] = {
            entry: previous_classifications.get(entry, DEFAULT_CLASS)
            for entry in entries
            if entry not in owned_by_fragments
        }

    invalid_classes = {
        classification
        for classifications in surfaces.values()
        for classification in classifications.values()
        if classification not in SURFACE_CLASSES
    }
    if invalid_classes:
        raise ValueError(f"unsupported surface classes: {sorted(invalid_classes)}")

    manifest = {"classes": sorted(SURFACE_CLASSES), "surfaces": surfaces}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    regenerate()
