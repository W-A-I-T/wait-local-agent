from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wait_local_agent.client_scope import AllClients
from wait_local_agent.store import Store


def test_store_releases_database_handles_after_startup_reads_and_writes(tmp_path: Path, monkeypatch) -> None:
    connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def tracked_connect(*args, **kwargs) -> sqlite3.Connection:
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    store = Store(tmp_path / "state.db")
    store.create_client("alpha", "Client Alpha")
    assert any(row.client_id == "alpha" for row in store.list_clients(AllClients()))
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("select 1")


def test_failed_store_transaction_rolls_back_and_releases_its_handle(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    with pytest.raises(RuntimeError, match="interrupted local operation"), store._connect() as connection:
        connection.execute(
            "insert into clients (client_id, name, created_at, updated_at) values (?, ?, ?, ?)",
            ("alpha", "Client Alpha", "2026-09-05T00:00:00Z", "2026-09-05T00:00:00Z"),
        )
        raise RuntimeError("interrupted local operation")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("select 1")
    restarted = Store(store.path)
    assert all(row.client_id != "alpha" for row in restarted.list_clients(AllClients()))


def test_connection_setup_failure_releases_handle(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")

    class FailedSetup(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("fixture PRAGMA failure")

    connection = sqlite3.connect(store.path, factory=FailedSetup)
    monkeypatch.setattr(sqlite3, "connect", lambda _path: connection)
    with pytest.raises(sqlite3.OperationalError, match="fixture PRAGMA failure"):
        store.list_clients(AllClients())
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.cursor()
