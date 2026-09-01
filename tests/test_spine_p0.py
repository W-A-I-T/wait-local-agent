from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TypedDict

import pytest
from fastapi import APIRouter, FastAPI, WebSocket
from starlette.routing import Mount, Route

from tests.support import ingest_local
from wait_local_agent.agents import AgentService
from wait_local_agent.api.app import create_app
from wait_local_agent.backup import backup_state, restore_state
from wait_local_agent.cli import app as cli_app
from wait_local_agent.migrations import Migration, MigrationRunner
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.surface_coverage import SURFACE_CLASSES, build_surface_inventory, enumerate_fastapi_routes

SURFACE_MANIFEST_PATH = Path(__file__).parents[1] / "docs/ai-workflow/surface-coverage.json"
SURFACE_MANIFEST_FRAGMENT_DIR = Path(__file__).parents[1] / "docs/ai-workflow/surface-coverage.d"


class SurfaceManifest(TypedDict):
    classes: list[str]
    surfaces: dict[str, dict[str, str]]


def _load_surface_manifest() -> SurfaceManifest:
    manifest = json.loads(SURFACE_MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_classes = sorted(SURFACE_CLASSES)
    assert manifest["classes"] == expected_classes
    classified: dict[str, dict[str, str]] = {
        surface_name: dict(entries)
        for surface_name, entries in manifest["surfaces"].items()
    }
    if SURFACE_MANIFEST_FRAGMENT_DIR.exists():
        for fragment_path in sorted(SURFACE_MANIFEST_FRAGMENT_DIR.glob("*.json")):
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            assert fragment["classes"] == expected_classes
            for surface_name, entries in fragment["surfaces"].items():
                target = classified.setdefault(surface_name, {})
                duplicates = set(target).intersection(entries)
                assert not duplicates, (
                    f"duplicate surface classifications in {fragment_path}: {sorted(duplicates)}"
                )
                target.update(entries)
    return {"classes": expected_classes, "surfaces": classified}


def test_store_migrations_are_idempotent_and_connection_pragmas_are_safe(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    Store(path)
    with Store(path)._connect() as connection:  # noqa: SLF001
        migration_columns = [str(row[1]) for row in connection.execute("pragma table_info(schema_migrations)")]
        assert migration_columns == ["version", "name", "applied_at"]
        assert [tuple(row) for row in connection.execute("select version, name from schema_migrations")] == [
            (0, "baseline"),
            (1, "principals"),
            (2, "clients_and_connectors"),
            (3, "provenance_and_ingestion"),
            (4, "canonical_assets_tenant_unique"),
            (5, "ticket_identity_and_tenancy"),
            (6, "poll_lease"),
            (7, "operational_graph"),
            (8, "auth_sessions_and_config"),
        ]
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
        assert connection.execute("pragma journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("pragma busy_timeout").fetchone()[0] >= 3000

    Store(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from schema_migrations").fetchone()[0] == 9


def test_migration_failure_rolls_back_data_and_version_bump(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "migrations.db")
    runner = MigrationRunner(connection)

    def failing_migration(active: sqlite3.Connection) -> None:
        active.execute("create table should_rollback (value text not null)")
        active.execute("insert into should_rollback values ('not committed')")
        raise RuntimeError("simulated migration crash")

    with pytest.raises(RuntimeError, match="simulated migration crash"):
        runner.run((Migration(1, "failing", failing_migration),))
    assert connection.execute("select count(*) from schema_migrations").fetchone()[0] == 0
    assert connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'should_rollback'"
    ).fetchone() is None

    def successful_migration(active: sqlite3.Connection) -> None:
        active.execute("create table committed (value text)")

    def noop_migration(active: sqlite3.Connection) -> None:
        active.execute("select 1")

    runner.run((Migration(1, "successful", successful_migration),))
    runner.run((Migration(1, "successful", noop_migration),))
    assert connection.execute("select version, name from schema_migrations").fetchall() == [(1, "successful")]
    connection.close()


def test_fresh_database_integrity_checks_are_clean(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    with store._connect() as connection:  # noqa: SLF001
        assert connection.execute("pragma foreign_key_check").fetchall() == []
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_backup_restore_round_trip_under_wal(tmp_path: Path) -> None:
    source = Store(tmp_path / "source.db")
    ingest_local(source, Path("examples/sample_tickets/tickets.json"))
    backup_path = tmp_path / "backup.db"
    restored_path = tmp_path / "restored.db"

    backup_state(source, backup_path)
    restore_state(Store(restored_path), backup_path)

    with Store(restored_path)._connect() as connection:  # noqa: SLF001
        assert connection.execute("select count(*) from tickets").fetchone()[0] > 0
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_surface_manifest_classifies_every_runtime_surface(settings) -> None:
    application = create_app(settings)
    store = application.state.store
    agent_service = AgentService(
        store,
        settings,
        SmartActionService(store, settings),
    )
    inventory = build_surface_inventory(
        application=application,
        cli_application=cli_app,
        agent_service=agent_service,
    )
    manifest = _load_surface_manifest()
    assert manifest["classes"] == sorted(SURFACE_CLASSES)
    classified = manifest["surfaces"]
    assert set(classified) == set(inventory)
    for surface_name, entries in inventory.items():
        assert set(entries) == set(classified[surface_name])
        assert all(classified[surface_name][entry] in SURFACE_CLASSES for entry in entries)


def test_surface_inventory_is_stable_for_a_fastapi_smoke_app() -> None:
    application = FastAPI()

    @application.get("/smoke")
    def smoke() -> dict[str, str]:
        return {"status": "ok"}

    assert "GET /smoke" in build_surface_inventory(
        application=application,
        cli_application=cli_app,
        agent_service=type("Catalog", (), {"list_tools": lambda self: []})(),
    )["fastapi_routes"]


def test_surface_inventory_expands_nested_included_router_prefixes() -> None:
    nested_router = APIRouter(prefix="/azure-lighthouse")

    @nested_router.get("/status")
    def nested_status() -> dict[str, bool]:
        return {"ok": True}

    @nested_router.websocket("/events")
    async def nested_events(websocket: WebSocket) -> None:
        return None

    parent_router = APIRouter()

    @parent_router.get("/status")
    def parent_status() -> dict[str, bool]:
        return {"ok": True}

    parent_router.include_router(nested_router)
    application = FastAPI()
    application.include_router(parent_router, prefix="/packs/microsoft-admin")

    def mounted_status() -> dict[str, bool]:
        return {"ok": True}

    application.router.routes.append(
        Mount("/mounted", routes=[Route("/status", mounted_status, methods=["GET"])])
    )

    @application.websocket("/root-events")
    async def root_events(websocket: WebSocket) -> None:
        return None

    inventory = enumerate_fastapi_routes(application)

    assert "GET /packs/microsoft-admin/azure-lighthouse/status" in inventory
    assert "GET /packs/microsoft-admin/status" in inventory
    assert "GET /mounted/status" in inventory
    assert not any(path.endswith("/events") for path in inventory)
    assert "GET /root-events" not in inventory
