from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

import wait_local_agent.store as store_module
from wait_local_agent.client_scope import AllClients
from wait_local_agent.models import Ticket
from wait_local_agent.store import Store, hash_credential


def _ticket(
    ticket_id: str,
    *,
    client_id: str | None = None,
    source_system: str | None = None,
    connector_instance_id: str | None = None,
    external_id: str | None = None,
    external_client_id: str | None = None,
) -> Ticket:
    return Ticket(
        id=ticket_id,
        client="Acme",
        subject="Test ticket",
        body="Ticket body",
        priority="Low",
        status="Open",
        client_id=client_id,
        source_system=source_system,
        connector_instance_id=connector_instance_id,
        external_id=external_id,
        external_client_id=external_client_id,
    )


def _active_instance(store: Store, *, client_id: str | None = None):
    instance = store.create_connector_instance("halopsa", "Primary Halo", client_id=client_id)
    active = store.update_connector_instance(instance.connector_instance_id, status="active")
    assert active is not None
    return active


def _verified_mapping(
    store: Store,
    connector_instance_id: str,
    external_company_id: str,
    client_id: str,
) -> None:
    mapping = store.create_client_connector_mapping(
        AllClients(), connector_instance_id, external_company_id, client_id
    )
    store.verify_client_connector_mapping(AllClients(), mapping.mapping_id)


def _provider_ticket(
    ticket_id: str,
    connector_instance_id: str,
    external_company_id: str,
    *,
    source_system: str = "halopsa",
) -> Ticket:
    return _ticket(
        ticket_id,
        source_system=source_system,
        connector_instance_id=connector_instance_id,
        external_id="remote-ticket",
        external_client_id=external_company_id,
    )


def test_local_ingest_requires_non_empty_client_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    with pytest.raises(ValueError, match="client_id must be non-empty"):
        store.ingest_tickets([_ticket("local-empty-client")], client_id="")


def test_local_ingest_rejects_ticket_client_conflict(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")

    with pytest.raises(ValueError, match="ticket client_id conflicts with the local ingestion tenant"):
        store.ingest_tickets(
            [_ticket("local-client-conflict", client_id="client-b")],
            client_id="client-a",
        )


def test_provider_ingest_requires_non_empty_connector_instance_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    with pytest.raises(ValueError, match="connector_instance_id must be non-empty"):
        store.ingest_provider_tickets([], connector_instance_id="")


def test_provider_ingest_rejects_unknown_connector_instance(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    with pytest.raises(KeyError):
        store.ingest_provider_tickets([], connector_instance_id="missing-instance")


def test_provider_ingest_requires_active_connector_instance(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("halopsa", "Inactive Halo")

    with pytest.raises(ValueError, match="connector instance must be active"):
        store.ingest_provider_tickets([], connector_instance_id=instance.connector_instance_id)


def test_provider_ingest_rejects_source_system_mismatch(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    instance = _active_instance(store)
    record = _provider_ticket(
        "provider-source-mismatch",
        instance.connector_instance_id,
        "company-a",
        source_system="hudu",
    )

    with pytest.raises(ValueError, match="provider source_system must match the connector type"):
        store.ingest_provider_tickets([record], connector_instance_id=instance.connector_instance_id)


def test_provider_ingest_requires_resolved_client_to_be_active(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    instance = _active_instance(store)
    _verified_mapping(store, instance.connector_instance_id, "company-a", "client-a")
    store.set_client_status(AllClients(), "client-a", "archived")
    record = _provider_ticket("provider-archived-client", instance.connector_instance_id, "company-a")

    with pytest.raises(ValueError, match="resolved client must be active"):
        store.ingest_provider_tickets([record], connector_instance_id=instance.connector_instance_id)


def test_provider_ingest_rejects_instance_client_mapping_conflict(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    instance = _active_instance(store, client_id="client-a")
    _verified_mapping(store, instance.connector_instance_id, "company-b", "client-b")
    record = _provider_ticket("provider-client-conflict", instance.connector_instance_id, "company-b")

    with pytest.raises(ValueError, match="connector instance client conflicts with the verified mapping"):
        store.ingest_provider_tickets([record], connector_instance_id=instance.connector_instance_id)


def test_local_ingest_rejects_null_client_before_writing(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    ticket = _ticket("local-null-client")
    real_replace = store_module.replace

    def replace_with_null_client(ticket_to_replace: Ticket, **changes: object) -> Ticket:
        effective = real_replace(ticket_to_replace, **changes)
        return real_replace(effective, client_id=None)

    with (
        patch.object(store_module, "replace", side_effect=replace_with_null_client),
        pytest.raises(ValueError, match="local tickets require a client_id"),
    ):
        store.ingest_tickets([ticket], client_id="client-a")


def test_local_ingest_rejects_takeover_of_connector_ticket(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    instance = _active_instance(store)
    _verified_mapping(store, instance.connector_instance_id, "company-a", "client-a")
    provider_ticket = _provider_ticket("shared-ticket-id", instance.connector_instance_id, "company-a")
    store.ingest_provider_tickets([provider_ticket], connector_instance_id=instance.connector_instance_id)
    persisted_ticket_id = store.list_tickets("client-a")[0].id

    with pytest.raises(ValueError, match="local ingestion cannot take over a connector ticket"):
        store.ingest_tickets([_ticket(persisted_ticket_id)], client_id="client-a")


def test_hash_credential_rejects_empty_credentials() -> None:
    for credential in ("", "   "):
        with pytest.raises(ValueError, match="credential must be a non-empty string"):
            hash_credential(credential)


class _MigrationCursor:
    def __init__(
        self,
        cursor: sqlite3.Cursor,
        *,
        fetchone_result: tuple[object, ...] | None = None,
        fetchall_result: list[tuple[object, ...]] | None = None,
        iterable_result: list[tuple[object, ...]] | None = None,
    ) -> None:
        self._cursor = cursor
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result
        self._iterable_result = iterable_result

    def fetchone(self) -> tuple[object, ...] | None:
        if self._fetchone_result is not None:
            return self._fetchone_result
        return self._cursor.fetchone()

    def fetchall(self) -> list[tuple[object, ...]]:
        if self._fetchall_result is not None:
            return self._fetchall_result
        return self._cursor.fetchall()

    def __iter__(self):
        if self._iterable_result is not None:
            return iter(self._iterable_result)
        return iter(self._cursor)

    def __getattr__(self, name: str):
        return getattr(self._cursor, name)


class _MigrationConnection:
    def __init__(self, connection: sqlite3.Connection, failure: str) -> None:
        self._connection = connection
        self._failure = failure
        self._count_queries = 0
        self._id_queries = 0

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor | _MigrationCursor:
        cursor = self._connection.execute(sql, parameters)
        normalized_sql = " ".join(sql.split()).lower()
        if normalized_sql == "select count(*) from tickets" and self._failure == "count":
            self._count_queries += 1
            if self._count_queries == 2:
                count = int(cursor.fetchone()[0])
                return _MigrationCursor(cursor, fetchone_result=(count + 1,))
        if normalized_sql == "select id from tickets" and self._failure == "ids":
            self._id_queries += 1
            if self._id_queries == 2:
                return _MigrationCursor(cursor, iterable_result=[*cursor, ("unexpected-ticket",)])
        if normalized_sql == "pragma foreign_key_check" and self._failure == "foreign_key":
            return _MigrationCursor(cursor, fetchall_result=[("tickets", 0, "clients", "id")])
        if normalized_sql == "pragma integrity_check" and self._failure == "integrity":
            return _MigrationCursor(cursor, fetchone_result=("not-ok",))
        return cursor


def _pre_v5_migration_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        create table clients (
            client_id text primary key,
            name text not null,
            status text not null,
            created_at text not null,
            updated_at text not null
        );
        create table connector_instances (
            connector_instance_id text primary key
        );
        create table unmapped_records (
            record_id text primary key,
            created_at text not null
        );
        create table tickets (
            id text primary key,
            client text not null,
            subject text not null,
            body text not null,
            priority text not null,
            status text not null
        );
        insert into tickets (id, client, subject, body, priority, status)
        values ('legacy-ticket', 'Acme', 'Subject', 'Body', 'Low', 'Open');
        """
    )
    return connection


def _assert_ticket_identity_migration_failure(failure: str, message: str) -> None:
    connection = _pre_v5_migration_connection()
    store = Store.__new__(Store)

    try:
        with pytest.raises(RuntimeError, match=message):
            store._apply_ticket_identity_migration(
                cast(sqlite3.Connection, _MigrationConnection(connection, failure)),
            )
    finally:
        connection.close()


def test_ticket_identity_migration_rejects_post_rebuild_count_change() -> None:
    _assert_ticket_identity_migration_failure("count", "ticket row count changed during v5 migration")


def test_ticket_identity_migration_rejects_post_rebuild_id_change() -> None:
    _assert_ticket_identity_migration_failure("ids", "ticket ids changed during v5 migration")


def test_ticket_identity_migration_rejects_post_rebuild_foreign_key_errors() -> None:
    _assert_ticket_identity_migration_failure("foreign_key", "ticket foreign-key check failed")


def test_ticket_identity_migration_rejects_post_rebuild_integrity_errors() -> None:
    _assert_ticket_identity_migration_failure(
        "integrity",
        "SQLite integrity check failed after v5 migration",
    )
