from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import Literal

import pytest

from wait_local_agent.store import (
    PollLeaseClaimResult,
    Store,
    SyncCursorLeaseConflictError,
)

NOW = "2026-08-16T12:00:00+00:00"
LIVE_NOW = "2099-08-16T12:00:00+00:00"
LAST_SYNCED = "2026-08-15T12:00:00+00:00"


def _seed_instance(path: Path) -> tuple[Store, str]:
    store = Store(path)
    store.create_client("client-a", "Acme")
    instance = store.create_connector_instance("halopsa", "Primary", client_id="client-a")
    return store, instance.connector_instance_id


def test_v6_registers_additive_lease_columns_and_preserves_foreign_keys(tmp_path: Path) -> None:
    store, _ = _seed_instance(tmp_path / "state.db")

    with store._connect() as connection:  # noqa: SLF001
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
        assert {str(row[1]) for row in connection.execute("pragma table_info(sync_cursors)")} >= {
            "lease_token",
            "lease_expires_at",
        }
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
        assert connection.execute("pragma foreign_key_check").fetchall() == []

        store._apply_poll_lease_migration(connection)  # noqa: SLF001
        assert connection.execute("pragma foreign_key_check").fetchall() == []


def test_claim_returns_tri_state_and_missing_instance_does_not_raise(tmp_path: Path) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")

    assert (
        store.claim_poll_lease(instance_id, "tickets", token="first", ttl_seconds=60, now=NOW)
        == PollLeaseClaimResult.GRANTED
    )
    assert (
        store.claim_poll_lease(instance_id, "tickets", token="first", ttl_seconds=60, now=NOW)
        == PollLeaseClaimResult.LOCKED
    )
    assert (
        store.claim_poll_lease(instance_id, "tickets", token="second", ttl_seconds=60, now=NOW)
        == PollLeaseClaimResult.LOCKED
    )
    assert (
        store.claim_poll_lease("missing", "tickets", token="missing", ttl_seconds=60, now=NOW)
        == PollLeaseClaimResult.INSTANCE_MISSING
    )
    assert (
        store.finish_poll_lease(
            "missing",
            "tickets",
            token="missing",
            status="failed",
            cursor_value=None,
            last_synced_at=None,
            now=NOW,
        )
        is False
    )


@pytest.mark.parametrize("connector_instance_id", ["", " "])
def test_claim_rejects_blank_connector_instance_id(tmp_path: Path, connector_instance_id: str) -> None:
    store, _ = _seed_instance(tmp_path / "state.db")

    with pytest.raises(ValueError, match="connector_instance_id"):
        store.claim_poll_lease(connector_instance_id, "tickets", token="token", ttl_seconds=60, now=NOW)


@pytest.mark.parametrize("cursor_type", ["", " "])
def test_claim_rejects_blank_cursor_type(tmp_path: Path, cursor_type: str) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")

    with pytest.raises(ValueError, match="cursor_type"):
        store.claim_poll_lease(instance_id, cursor_type, token="token", ttl_seconds=60, now=NOW)


@pytest.mark.parametrize("ttl_seconds", [0.0, -1.0, float("inf"), float("nan")])
def test_claim_rejects_invalid_ttl(tmp_path: Path, ttl_seconds: float) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")

    with pytest.raises(ValueError, match="ttl_seconds"):
        store.claim_poll_lease(instance_id, "tickets", token="token", ttl_seconds=ttl_seconds, now=NOW)


def test_concurrent_claims_grant_exactly_one_real_connection(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store, instance_id = _seed_instance(path)
    barrier = threading.Barrier(2)
    results: Queue[PollLeaseClaimResult] = Queue()
    errors: Queue[BaseException] = Queue()

    def claim(token: str) -> None:
        try:
            barrier.wait()
            results.put(
                Store(path).claim_poll_lease(
                    instance_id,
                    "tickets",
                    token=token,
                    ttl_seconds=60,
                    now=NOW,
                )
            )
        except BaseException as exc:  # pragma: no cover - assertion below reports unexpected thread failures
            errors.put(exc)

    threads = [threading.Thread(target=claim, args=(token,)) for token in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors.empty()
    observed = [results.get_nowait(), results.get_nowait()]
    assert observed.count(PollLeaseClaimResult.GRANTED) == 1
    assert observed.count(PollLeaseClaimResult.LOCKED) == 1
    assert store.get_sync_cursor(instance_id, "tickets") is not None


def test_claim_preserves_progress_and_takes_over_expired_and_legacy_leases(tmp_path: Path) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")
    store.upsert_sync_cursor(
        instance_id,
        "tickets",
        cursor_value="offset-1",
        status="idle",
        last_synced_at=LAST_SYNCED,
    )

    assert store.claim_poll_lease(instance_id, "tickets", token="first", ttl_seconds=60, now=NOW) == (
        PollLeaseClaimResult.GRANTED
    )
    cursor = store.get_sync_cursor(instance_id, "tickets")
    assert cursor is not None
    assert cursor.cursor_value == "offset-1"
    assert cursor.last_synced_at == LAST_SYNCED

    expired = (datetime.fromisoformat(NOW).replace(tzinfo=UTC) - timedelta(seconds=1)).isoformat()
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update sync_cursors set lease_expires_at = ? where connector_instance_id = ?",
            (expired, instance_id),
        )
    assert store.claim_poll_lease(instance_id, "tickets", token="second", ttl_seconds=60, now=NOW) == (
        PollLeaseClaimResult.GRANTED
    )

    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update sync_cursors set status = 'syncing', lease_expires_at = null where connector_instance_id = ?",
            (instance_id,),
        )
    assert store.claim_poll_lease(instance_id, "tickets", token="legacy", ttl_seconds=60, now=NOW) == (
        PollLeaseClaimResult.GRANTED
    )


@pytest.mark.parametrize("terminal_status", ["degraded", "failed"])
def test_stale_finish_cannot_modify_successor_and_terminal_release_preserves_history(
    tmp_path: Path, terminal_status: Literal["degraded", "failed"]
) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")
    store.upsert_sync_cursor(
        instance_id,
        "tickets",
        cursor_value="old-offset",
        status="idle",
        last_synced_at=LAST_SYNCED,
    )
    assert store.claim_poll_lease(instance_id, "tickets", token="stale", ttl_seconds=60, now=NOW) == (
        PollLeaseClaimResult.GRANTED
    )
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update sync_cursors set lease_expires_at = ? where connector_instance_id = ?",
            ((datetime.fromisoformat(NOW) - timedelta(seconds=1)).isoformat(), instance_id),
        )
    assert store.claim_poll_lease(instance_id, "tickets", token="successor", ttl_seconds=60, now=NOW) == (
        PollLeaseClaimResult.GRANTED
    )

    assert (
        store.finish_poll_lease(
            instance_id,
            "tickets",
            token="stale",
            status="idle",
            cursor_value="stale-write",
            last_synced_at="stale-write",
            now=NOW,
        )
        is False
    )
    protected = store.get_sync_cursor(instance_id, "tickets")
    assert protected is not None
    assert protected.status == "syncing"
    assert protected.cursor_value == "old-offset"
    assert protected.last_synced_at == LAST_SYNCED

    assert store.finish_poll_lease(
        instance_id,
        "tickets",
        token="successor",
        status=terminal_status,
        cursor_value="new-offset",
        last_synced_at=LAST_SYNCED,
        now=NOW,
    )
    finished = store.get_sync_cursor(instance_id, "tickets")
    assert finished is not None
    assert finished.status == terminal_status
    assert finished.cursor_value == "new-offset"
    assert finished.last_synced_at == LAST_SYNCED
    with store._connect() as connection:  # noqa: SLF001
        lease = connection.execute(
            "select lease_token, lease_expires_at from sync_cursors "
            "where connector_instance_id = ? and cursor_type = ?",
            (instance_id, "tickets"),
        ).fetchone()
    assert lease is not None
    assert tuple(lease) == (None, None)


def test_public_cursor_reads_and_upsert_never_hydrate_or_expose_lease_fields(tmp_path: Path) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")
    persisted = store.upsert_sync_cursor(instance_id, "tickets", cursor_value="offset", status="idle")
    assert persisted.cursor_value == "offset"
    assert store.get_sync_cursor(instance_id, "tickets") == persisted
    assert store.list_sync_cursors() == [persisted]

    assert store.claim_poll_lease(instance_id, "tickets", token="live", ttl_seconds=60, now=LIVE_NOW) == (
        PollLeaseClaimResult.GRANTED
    )
    with pytest.raises(SyncCursorLeaseConflictError, match="active poll lease"):
        store.upsert_sync_cursor(instance_id, "tickets", cursor_value="clobbered", status="failed")

    for cursor in [store.get_sync_cursor(instance_id, "tickets"), *store.list_sync_cursors()]:
        assert cursor is not None
        assert not hasattr(cursor, "lease_token")
        assert not hasattr(cursor, "lease_expires_at")
        assert cursor.cursor_value == "offset"


def test_upsert_proceeds_for_absent_and_expired_leases(tmp_path: Path) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")

    first = store.upsert_sync_cursor(instance_id, "tickets", cursor_value="offset-1", status="idle")
    assert first.cursor_value == "offset-1"
    updated_without_lease = store.upsert_sync_cursor(
        instance_id, "tickets", cursor_value="offset-2", status="idle", last_synced_at=LAST_SYNCED
    )
    assert updated_without_lease.cursor_value == "offset-2"
    assert updated_without_lease.last_synced_at == LAST_SYNCED

    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update sync_cursors set status = 'syncing', lease_token = ?, lease_expires_at = ? "
            "where connector_instance_id = ? and cursor_type = ?",
            ("expired-token", "2000-01-01T00:00:00+00:00", instance_id, "tickets"),
        )

    proceeded = store.upsert_sync_cursor(instance_id, "tickets", cursor_value="offset-3", status="idle")
    assert proceeded.cursor_value == "offset-3"
    with store._connect() as connection:  # noqa: SLF001
        lease = connection.execute(
            "select lease_token, lease_expires_at from sync_cursors "
            "where connector_instance_id = ? and cursor_type = ?",
            (instance_id, "tickets"),
        ).fetchone()
    assert lease is not None
    assert tuple(lease) == (None, None)


@pytest.mark.parametrize("connector_instance_id", ["", " "])
def test_upsert_rejects_blank_connector_instance_id(tmp_path: Path, connector_instance_id: str) -> None:
    store, _ = _seed_instance(tmp_path / "state.db")

    with pytest.raises(ValueError, match="connector_instance_id"):
        store.upsert_sync_cursor(connector_instance_id, "tickets", cursor_value=None)


@pytest.mark.parametrize("cursor_type", ["", " "])
def test_upsert_rejects_blank_cursor_type(tmp_path: Path, cursor_type: str) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")

    with pytest.raises(ValueError, match="cursor_type"):
        store.upsert_sync_cursor(instance_id, cursor_type, cursor_value=None)


def test_upsert_rejects_unsupported_status(tmp_path: Path) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")

    with pytest.raises(ValueError, match="unsupported sync cursor status"):
        store.upsert_sync_cursor(instance_id, "tickets", cursor_value=None, status="bogus")


def test_upsert_rejects_nonexistent_connector_instance(tmp_path: Path) -> None:
    store, _ = _seed_instance(tmp_path / "state.db")

    with pytest.raises(KeyError):
        store.upsert_sync_cursor("missing", "tickets", cursor_value=None)


def test_get_sync_cursor_returns_none_for_missing_row(tmp_path: Path) -> None:
    store, instance_id = _seed_instance(tmp_path / "state.db")

    assert store.get_sync_cursor(instance_id, "tickets") is None
    assert store.get_sync_cursor(instance_id, "") is None
