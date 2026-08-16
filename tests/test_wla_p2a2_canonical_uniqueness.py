from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wait_local_agent.migrations import Migration, MigrationRunner
from wait_local_agent.store import Store


def _build_pre_v4_database(path: Path) -> None:
    store = Store.__new__(Store)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    MigrationRunner(connection).run(
        (
            Migration(0, "baseline", store._apply_baseline_migration),
            Migration(1, "principals", store._apply_principals_migration),
            Migration(2, "clients_and_connectors", store._apply_clients_migration),
            Migration(3, "provenance_and_ingestion", store._apply_provenance_migration),
        )
    )
    connection.execute(
        "insert into collector_runs "
        "(id, module_id, status, mode, scope_json, preview_json, started_at, client_id) "
        "values (301, 'fixture', 'completed', 'confirmed', '{}', '{}', 'now', 'client-a')"
    )
    connection.execute(
        "insert into canonical_assets "
        "(id, canonical_id, asset_type, display_name, client_id, first_seen, last_seen, attributes_json) "
        "values (101, 'asset-a', 'server', 'Asset A', 'client-a', 'now', 'now', '{}')"
    )
    connection.execute(
        "insert into canonical_assets "
        "(id, canonical_id, asset_type, display_name, client_id, first_seen, last_seen, attributes_json) "
        "values (205, 'asset-b', 'endpoint', 'Asset B', 'client-b', 'now', 'now', '{}')"
    )
    connection.execute(
        "insert into asset_observations "
        "(id, asset_id, run_id, observed_at, observation_type, payload_json) "
        "values (401, 101, 301, 'now', 'inventory', '{}')"
    )
    connection.execute("create index idx_canonical_assets_source on canonical_assets(source_module)")
    connection.commit()
    connection.close()


def test_migration_framework_toggles_and_restores_foreign_keys() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("pragma foreign_keys = on")
    observed: list[int] = []

    def successful(active: sqlite3.Connection) -> None:
        observed.append(int(active.execute("pragma foreign_keys").fetchone()[0]))
        active.execute("create table completed (value text)")

    MigrationRunner(connection).run((Migration(1, "fk-off-success", successful, foreign_keys_off=True),))
    assert observed == [0]
    assert connection.execute("pragma foreign_keys").fetchone()[0] == 1

    def failing(active: sqlite3.Connection) -> None:
        observed.append(int(active.execute("pragma foreign_keys").fetchone()[0]))
        active.execute("create table rolled_back (value text)")
        raise RuntimeError("fk-off migration failed")

    with pytest.raises(RuntimeError, match="fk-off migration failed"):
        MigrationRunner(connection).run((Migration(2, "fk-off-failure", failing, foreign_keys_off=True),))
    assert observed == [0, 0]
    assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
    assert connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'rolled_back'"
    ).fetchone() is None
    connection.close()


def test_v4_rebuild_preserves_asset_ids_observations_indexes_and_counts(tmp_path: Path) -> None:
    path = tmp_path / "pre-v4.db"
    _build_pre_v4_database(path)

    store = Store(path)
    with store._connect() as connection:  # noqa: SLF001
        assert connection.execute("select count(*) from canonical_assets").fetchone()[0] == 2
        assert connection.execute("select count(*) from asset_observations").fetchone()[0] == 1
        assert {
            int(row[0]) for row in connection.execute("select id from canonical_assets")
        } == {101, 205}
        assert connection.execute(
            "select asset_id from asset_observations where id = 401"
        ).fetchone()[0] == 101
        assert connection.execute(
            "select 1 from sqlite_master where type = 'index' and name = 'idx_canonical_assets_source'"
        ).fetchone() is not None
        assert connection.execute("pragma foreign_key_check").fetchall() == []
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1

        before = connection.execute(
            "select id, canonical_id, client_id from canonical_assets order by id"
        ).fetchall()
        store._apply_canonical_tenant_unique_migration(connection)  # noqa: SLF001
        assert connection.execute(
            "select id, canonical_id, client_id from canonical_assets order by id"
        ).fetchall() == before
        assert connection.execute("pragma foreign_key_check").fetchall() == []

        unique_indexes = [
            row
            for row in connection.execute("pragma index_list('canonical_assets')")
            if bool(row[2])
        ]
        assert any(
            [
                str(column[2])
                for column in connection.execute(
                    f"pragma index_info('{index_row[1]}')"  # nosec B608: metadata name is quoted
                )
            ]
            == ["client_id", "canonical_id"]
            for index_row in unique_indexes
        )
        assert all(
            [
                str(column[2])
                for column in connection.execute(
                    f"pragma index_info('{index_row[1]}')"  # nosec B608: metadata name is quoted
                )
            ]
            != ["canonical_id"]
            for index_row in unique_indexes
        )
        assert connection.execute("pragma table_info('canonical_assets')").fetchall()[1][3] == 1


def test_v4_rejects_preexisting_duplicate_tenant_pairs(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "duplicates.db")
    connection.execute("pragma foreign_keys = on")
    connection.execute(
        """
        create table canonical_assets (
            id integer primary key autoincrement,
            canonical_id text not null,
            asset_type text not null,
            display_name text not null,
            client_id text,
            owner text not null default '',
            source_module text not null default '',
            source_id text not null default '',
            confidence real not null default 1.0,
            first_seen text not null,
            last_seen text not null,
            attributes_json text not null
        )
        """
    )
    connection.execute(
        "insert into canonical_assets "
        "(id, canonical_id, asset_type, display_name, client_id, first_seen, last_seen, attributes_json) "
        "values (1, 'duplicate-a', 'server', 'A', 'client-a', 'now', 'now', '{}')"
    )
    connection.execute(
        "insert into canonical_assets "
        "(id, canonical_id, asset_type, display_name, client_id, first_seen, last_seen, attributes_json) "
        "values (2, 'duplicate-a', 'server', 'B', 'client-a', 'now', 'now', '{}')"
    )
    connection.commit()
    store = Store.__new__(Store)
    with pytest.raises(RuntimeError, match=r"duplicate \(client_id, canonical_id\) pairs"):
        MigrationRunner(connection).run(
            (
                Migration(
                    4,
                    "canonical_assets_tenant_unique",
                    store._apply_canonical_tenant_unique_migration,
                    foreign_keys_off=True,
                ),
            )
        )
    assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
    assert connection.execute("select count(*) from canonical_assets").fetchone()[0] == 2
    assert connection.execute("select count(*) from schema_migrations").fetchone()[0] == 0
    connection.close()


def test_canonical_asset_upsert_and_lookup_are_tenant_aware(settings) -> None:
    store = Store(settings.data_path)

    first = store.upsert_canonical_asset(
        canonical_id="shared-asset",
        asset_type="server",
        display_name="Acme original",
        attributes={"version": 1},
        client_id="client-a",
    )
    updated = store.upsert_canonical_asset(
        canonical_id="shared-asset",
        asset_type="endpoint",
        display_name="Acme updated",
        attributes={"version": 2},
        client_id="client-a",
    )
    beta = store.upsert_canonical_asset(
        canonical_id="shared-asset",
        asset_type="server",
        display_name="Beta asset",
        attributes={"version": 1},
        client_id="client-b",
    )

    assert updated.id == first.id
    assert updated.display_name == "Acme updated"
    assert beta.id != first.id
    assert store.get_canonical_asset_by_canonical_id("shared-asset", client_id="client-a") == updated
    assert store.get_canonical_asset_by_canonical_id("shared-asset", client_id="client-b") == beta
    unscoped = store.get_canonical_asset_by_canonical_id("shared-asset")
    assert unscoped is not None
    assert unscoped.id == first.id
    with store._connect() as connection:  # noqa: SLF001
        assert connection.execute(
            "select count(*) from canonical_assets where canonical_id = 'shared-asset'"
        ).fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into canonical_assets "
                "(canonical_id, asset_type, display_name, client_id, first_seen, last_seen, attributes_json) "
                "values ('shared-asset', 'server', 'duplicate', 'client-a', 'now', 'now', '{}')"
            )


def test_null_client_upsert_preserves_legacy_canonical_fallback(settings) -> None:
    store = Store(settings.data_path)

    tenant_asset = store.upsert_canonical_asset(
        canonical_id="legacy-asset",
        asset_type="server",
        display_name="Original",
        attributes={},
        client_id="client-a",
    )
    null_update = store.upsert_canonical_asset(
        canonical_id="legacy-asset",
        asset_type="endpoint",
        display_name="Updated without client",
        attributes={"legacy": True},
    )
    null_repeat = store.upsert_canonical_asset(
        canonical_id="null-only-asset",
        asset_type="server",
        display_name="Null original",
        attributes={},
    )
    null_repeat_updated = store.upsert_canonical_asset(
        canonical_id="null-only-asset",
        asset_type="endpoint",
        display_name="Null updated",
        attributes={"updated": True},
    )

    assert null_update.id == tenant_asset.id
    assert null_update.client_id == "client-a"
    assert null_repeat_updated.id == null_repeat.id
    assert null_repeat_updated.client_id is None
    assert store.get_canonical_asset_by_canonical_id("legacy-asset", client_id="client-a") == null_update
