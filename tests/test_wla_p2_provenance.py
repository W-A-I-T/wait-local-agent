from __future__ import annotations

import json
from pathlib import Path

from wait_local_agent.client_scope import AllClients, BoundClients
from wait_local_agent.models import Ticket
from wait_local_agent.store import Store


def _seed_connectors(store: Store):
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    connector_a = store.create_connector_instance("halopsa", "Acme", client_id="client-a")
    connector_b = store.create_connector_instance("halopsa", "Beta", client_id="client-b")
    store.update_connector_instance(connector_a.connector_instance_id, status="active")
    store.update_connector_instance(connector_b.connector_instance_id, status="active")
    return connector_a, connector_b


def test_v3_is_additive_idempotent_and_fk_clean(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    with store._connect() as connection:  # noqa: SLF001
        columns = {str(row[1]) for row in connection.execute("pragma table_info(tickets)")}
        assert columns >= {
            "source_system",
            "connector_instance_id",
            "external_id",
            "external_client_id",
        }
        assert connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'sync_cursors'"
        ).fetchone()
        assert connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'unmapped_records'"
        ).fetchone()

        canonical_indexes = [
            row
            for row in connection.execute("pragma index_list(canonical_assets)")
            if bool(row[2])
        ]
        assert any(
            [
                str(index_column[2])
                for index_column in connection.execute(
                    f"pragma index_info('{index_row[1]}')"  # nosec B608: index name comes from SQLite metadata
                )
            ]
            == ["client_id", "canonical_id"]
            for index_row in canonical_indexes
        )
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1

        before_versions = connection.execute(
            "select version, name from schema_migrations order by version"
        ).fetchall()
        store._apply_provenance_migration(connection)  # noqa: SLF001
        after_versions = connection.execute(
            "select version, name from schema_migrations order by version"
        ).fetchall()
        assert after_versions == before_versions
        assert connection.execute("pragma foreign_key_check").fetchall() == []

    Store(tmp_path / "state.db")
    with store._connect() as connection:  # noqa: SLF001
        assert connection.execute("select count(*) from schema_migrations").fetchone()[0] == 12
        assert connection.execute("pragma foreign_key_check").fetchall() == []


def test_ticket_provenance_columns_accept_return_and_enforce_scope(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    connector_a, _ = _seed_connectors(store)
    ticket_path = tmp_path / "tickets.json"
    ticket_path.write_text(
        json.dumps(
            [
                {
                    "id": "TCK-PROVENANCE",
                    "client": "Acme",
                    "subject": "Imported",
                    "body": "Body",
                    "priority": "Low",
                    "status": "Open",
                    "client_id": None,
                    "source_system": "halopsa",
                    "connector_instance_id": connector_a.connector_instance_id,
                    "external_id": "remote-1",
                    "external_client_id": "company-1",
                }
            ]
        ),
        encoding="utf-8",
    )

    mapping = store.create_client_connector_mapping(
        AllClients(), connector_a.connector_instance_id, "company-1", "client-a"
    )
    store.verify_client_connector_mapping(AllClients(), mapping.mapping_id)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets
              (id, client, subject, body, priority, status, client_id, source_system,
               connector_instance_id, external_id, external_client_id)
            values ('TCK-PROVENANCE', 'Acme', 'Imported', 'Body', 'Low', 'Open', 'client-a',
                    'halopsa', ?, 'remote-1', 'company-1')
            """,
            (connector_a.connector_instance_id,),
        )
    provider_ticket = Ticket(**json.loads(ticket_path.read_text(encoding="utf-8"))[0])
    assert store.ingest_provider_tickets(
        [provider_ticket], connector_instance_id=connector_a.connector_instance_id
    ).written == 1
    ticket = store.get_ticket("TCK-PROVENANCE", "client-a")
    assert ticket is not None
    assert ticket.source_system == "halopsa"
    assert ticket.connector_instance_id == connector_a.connector_instance_id
    assert ticket.external_id == "remote-1"
    assert ticket.external_client_id == "company-1"
    assert ticket.id == "TCK-PROVENANCE"
    assert store.get_ticket("TCK-PROVENANCE", "client-b") is None
    assert store.list_tickets(BoundClients(frozenset({"client-b"}))) == []

    local = store.create_end_user_ticket(
        client_id="client-a",
        requester_id="requester",
        subject="Local",
        body="Body",
    )
    assert local.source_system == "local"
    assert local.connector_instance_id is None


def test_sync_cursors_upsert_and_status(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    connector_a, connector_b = _seed_connectors(store)

    first = store.upsert_sync_cursor(
        connector_a.connector_instance_id,
        "tickets",
        cursor_value="1",
        status="SYNCING",
        last_synced_at="2026-08-15T00:00:00+00:00",
    )
    updated = store.upsert_sync_cursor(
        connector_a.connector_instance_id,
        "tickets",
        cursor_value="2",
        status="idle",
    )
    other = store.upsert_sync_cursor(
        connector_b.connector_instance_id,
        "tickets",
        cursor_value=None,
        status="degraded",
    )

    assert first.status == "syncing"
    assert updated.cursor_value == "2"
    assert updated.status == "idle"
    assert updated.last_synced_at is None
    assert store.get_sync_cursor(connector_a.connector_instance_id, "tickets") == updated
    assert store.get_sync_cursor(connector_a.connector_instance_id, "missing") is None
    assert {cursor.connector_instance_id for cursor in store.list_sync_cursors()} == {
        connector_a.connector_instance_id,
        connector_b.connector_instance_id,
    }
    assert other.status == "degraded"


def test_unmapped_records_record_list_resolve_and_scope(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    connector_a, connector_b = _seed_connectors(store)

    first = store.record_unmapped(
        connector_a.connector_instance_id,
        "company-a",
        "ticket-a",
        "ticket",
        "digest-a",
        "no_verified_mapping",
    )
    second = store.record_unmapped(
        connector_b.connector_instance_id,
        None,
        "ticket-b",
        "ticket",
        None,
        "ambiguous_mapping",
    )

    assert store.list_unmapped_records(BoundClients(frozenset({"client-a"}))) == [first]
    assert store.list_unmapped_records(BoundClients(frozenset({"client-b"}))) == [second]
    assert store.list_unmapped_records(
        BoundClients(frozenset({"client-a"})),
        connector_instance_id=connector_b.connector_instance_id,
    ) == []
    assert {record.record_id for record in store.list_unmapped_records(AllClients())} == {
        first.record_id,
        second.record_id,
    }

    resolved = store.resolve_unmapped_record(first.record_id)
    assert resolved is not None
    assert resolved.resolved_at is not None
    assert store.resolve_unmapped_record("missing") is None
    assert store.list_unmapped_records(BoundClients(frozenset({"client-a"})))[0].resolved_at is not None
