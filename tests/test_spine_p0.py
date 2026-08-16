from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI

from wait_local_agent.agents import AgentService
from wait_local_agent.api.app import create_app
from wait_local_agent.backup import backup_state, restore_state
from wait_local_agent.cli import app as cli_app
from wait_local_agent.migrations import Migration, MigrationRunner
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.surface_coverage import SURFACE_CLASSES, build_surface_inventory

SURFACE_MANIFEST_PATH = Path(__file__).parents[1] / "docs/ai-workflow/surface-coverage.json"


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
        ]
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
        assert connection.execute("pragma journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("pragma busy_timeout").fetchone()[0] >= 3000

    Store(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from schema_migrations").fetchone()[0] == 3


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
    source.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
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
    manifest = json.loads(SURFACE_MANIFEST_PATH.read_text(encoding="utf-8"))
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
