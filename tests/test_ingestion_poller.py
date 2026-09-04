from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

import wait_local_agent.ingestion_poller as poller_module
from tests.support import ensure_test_clients
from wait_local_agent.client_scope import AllClients
from wait_local_agent.connector_factory import ConnectorFactoryError
from wait_local_agent.connectwise import ConnectWiseReadError
from wait_local_agent.halopsa import HaloReadError
from wait_local_agent.ingestion_poller import IngestionPoller
from wait_local_agent.models import (
    ConnectorStatusValue,
    HaloReadResponse,
    HaloReadResult,
    HaloTicket,
    IngestSummary,
    Ticket,
)
from wait_local_agent.store import PollLeaseClaimResult, Store

NOW = "2026-08-16T12:00:00+00:00"


@dataclass
class _Clock:
    monotonic_value: float = 0.0

    def wall(self) -> str:
        return NOW

    def monotonic(self) -> float:
        return self.monotonic_value


class _HaloPages:
    def __init__(self, pages: list[HaloReadResponse]) -> None:
        self.pages = pages
        self.calls: list[tuple[int, int]] = []

    def list_tickets(self, page: int, page_size: int) -> HaloReadResponse:
        self.calls.append((page, page_size))
        return self.pages[min(page - 1, len(self.pages) - 1)]


class _RetryThenEmpty:
    def __init__(self, transient: HaloReadResponse) -> None:
        self.transient = transient
        self.calls = 0

    def list_tickets(self, page: int, page_size: int) -> HaloReadResponse:
        self.calls += 1
        return self.transient if self.calls == 1 else _response([], raw_count=0)


class _RaisingAdapter(poller_module.ProviderTicketAdapter):
    def __init__(self, error: Exception) -> None:
        super().__init__("instance")
        self.error = error
        self.calls = 0

    def fetch_page(
        self,
        client: poller_module.TicketListClient,
        *,
        page: int,
        page_size: int,
    ) -> poller_module.ProviderPage:
        self.calls += 1
        raise self.error


def _ticket(external_id: str, company_id: str = "company-a") -> HaloTicket:
    return HaloTicket(external_id, f"Subject {external_id}", "Open", "High", company_id, "Acme")


def _response(
    items: list[HaloTicket],
    *,
    raw_count: int | None = None,
    dropped_count: int = 0,
    status: str = "ready",
    http_status: int | None = 200,
    retry_after: float | None = None,
) -> HaloReadResponse:
    return HaloReadResponse(
        HaloReadResult(cast(ConnectorStatusValue, status), "provider message", len(items)),
        cast(list[HaloTicket | Any], items),
        raw_count=len(items) if raw_count is None else raw_count,
        dropped_count=dropped_count,
        http_status=http_status,
        retry_after=retry_after,
    )


def _seed_store(tmp_path: Path, connector_type: str = "halopsa") -> tuple[Store, str]:
    store = Store(tmp_path / "state.db")
    ensure_test_clients(store, "client-a")
    instance = store.create_connector_instance(connector_type, "Primary")
    active = store.update_connector_instance(instance.connector_instance_id, status="active")
    assert active is not None
    store.create_client_connector_mapping(
        AllClients(),
        active.connector_instance_id,
        "company-a",
        "client-a",
    )
    mappings = store.list_client_connector_mappings(
        AllClients(),
        connector_instance_id=active.connector_instance_id,
    )
    store.verify_client_connector_mapping(AllClients(), mappings[0].mapping_id)
    return store, active.connector_instance_id


def _poller(store: Store, client: object, clock: _Clock | None = None, **kwargs: Any) -> IngestionPoller:
    active_clock = clock or _Clock()
    builder = kwargs.pop("client_builder", lambda _store, _instance_id: client)
    timeout = kwargs.pop("connector_timeout_seconds", 1.0)
    return IngestionPoller(
        store,
        client_builder=builder,
        connector_timeout_seconds=timeout,
        wall_clock=active_clock.wall,
        monotonic_clock=active_clock.monotonic,
        sleeper=lambda _seconds: None,
        **kwargs,
    )


def _poll(poller: IngestionPoller, *, max_pages: int = 5, deadline_seconds: float = 10.0):
    return poller.poll_instance(
        "instance-placeholder",
        max_pages=max_pages,
        page_size=25,
        deadline_seconds=deadline_seconds,
        lease_ttl_seconds=100.0,
    )


def test_stop_requires_ready_2xx_empty_page_and_happy_poll_finishes_idle(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    client = _HaloPages([_response([_ticket("one")]), _response([], raw_count=0)])
    poller = _poller(store, client)

    summary = poller.poll_instance(
        instance_id, max_pages=5, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )

    assert summary.status == "idle"
    assert summary.pages_fetched == 2
    assert summary.written == 1
    assert summary.quarantined == 0
    cursor = store.get_sync_cursor(instance_id, "connector_poll")
    assert cursor is not None
    assert cursor.status == "idle"
    assert cursor.cursor_value == "2"
    assert cursor.last_synced_at == NOW
    assert client.calls == [(1, 25), (2, 25)]


def test_all_dropped_page_continues_and_is_degraded(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    client = _HaloPages(
        [
            _response([], raw_count=2, dropped_count=2),
            _response([], raw_count=0),
        ]
    )
    summary = _poller(store, client).poll_instance(
        instance_id, max_pages=5, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )
    assert summary.status == "degraded"
    assert summary.reason == "dropped_rows"
    assert summary.pages_fetched == 2


def test_transient_retry_then_clean_eof_remains_degraded(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    client = _RetryThenEmpty(_response([], raw_count=0, http_status=503, retry_after=0))
    summary = _poller(store, client).poll_instance(
        instance_id, max_pages=2, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )
    assert summary.status == "degraded"
    assert summary.reason == "transient_provider"
    assert client.calls == 2


def test_repoll_is_idempotent(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    client = _HaloPages([_response([_ticket("one")]), _response([], raw_count=0)])
    poller = _poller(store, client)

    first = poller.poll_instance(instance_id, max_pages=5, page_size=25, deadline_seconds=10, lease_ttl_seconds=100)
    second = poller.poll_instance(instance_id, max_pages=5, page_size=25, deadline_seconds=10, lease_ttl_seconds=100)

    assert first.status == second.status == "idle"
    assert len(store.list_tickets("client-a")) == 1
    assert second.written == 1


def test_locked_claim_is_skipped_without_cursor_write(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    assert store.claim_poll_lease(
        instance_id,
        "connector_poll",
        token="owner",
        ttl_seconds=100,
        now=NOW,
    ) == PollLeaseClaimResult.GRANTED
    client = _HaloPages([_response([], raw_count=0)])

    summary = _poller(store, client).poll_instance(
        instance_id, max_pages=5, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )

    assert summary.status == "skipped_locked"
    assert client.calls == []
    cursor = store.get_sync_cursor(instance_id, "connector_poll")
    assert cursor is not None and cursor.status == "syncing"


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (_response([], status="blocked", http_status=None), "degraded"),
        (_response([], status="ready", http_status=429, retry_after=0), "degraded"),
        (_response([], status="failed", http_status=408), "degraded"),
        (_response([], status="failed", http_status=503), "degraded"),
        (_response([], status="failed", http_status=401), "failed"),
        (_response([], status="configured", http_status=200), "failed"),
        (_response([], status="not_configured", http_status=None), "failed"),
        (_response([], status="failed", http_status=302), "failed"),
    ],
)
def test_failure_taxonomy(tmp_path: Path, response: HaloReadResponse, expected_status: str) -> None:
    store, instance_id = _seed_store(tmp_path)
    summary = _poller(store, _HaloPages([response])).poll_instance(
        instance_id, max_pages=1, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )
    assert summary.status == expected_status


def test_factory_failure_and_missing_instance_never_raise(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    poller = IngestionPoller(
        store,
        client_builder=lambda _store, _instance_id: (_ for _ in ()).throw(RuntimeError("secret")),
        connector_timeout_seconds=1.0,
        wall_clock=lambda: NOW,
        monotonic_clock=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )
    summary = poller.poll_instance("missing", max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63)
    assert summary.status == "failed"
    assert summary.reason == "instance_missing"


def test_failure_boundaries_and_inactive_instance_are_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, instance_id = _seed_store(tmp_path)
    monkeypatch.setattr(
        store,
        "claim_poll_lease",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    summary = _poller(store, _HaloPages([])).poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "failed" and summary.reason == "poll_error"

    inactive = store.update_connector_instance(instance_id, status="inactive")
    assert inactive is not None
    monkeypatch.setattr(store, "claim_poll_lease", Store.claim_poll_lease.__get__(store))
    summary = _poller(store, _HaloPages([])).poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "failed" and summary.reason == "inactive_instance"


def test_unsupported_and_factory_failures_do_not_raise(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path, connector_type="unknown")
    summary = _poller(store, _HaloPages([])).poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "failed" and summary.reason == "unsupported_connector"

    factory_path = tmp_path / "factory"
    factory_path.mkdir()
    store, instance_id = _seed_store(factory_path)
    poller = _poller(store, _HaloPages([]), client_builder=lambda *_args: (_ for _ in ()).throw(RuntimeError("secret")))
    summary = poller.poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "failed" and summary.reason == "factory_error"


def test_deadline_and_sink_failure_are_terminal_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, instance_id = _seed_store(tmp_path)
    class _ExpiredClock(_Clock):
        calls = 0

        def monotonic(self) -> float:
            self.calls += 1
            return 0.0 if self.calls == 1 else 2.0

    clock = _ExpiredClock()
    summary = _poller(store, _HaloPages([_response([], raw_count=0)]), clock).poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "degraded" and summary.reason == "deadline_exhausted"

    store, instance_id = _seed_store(tmp_path / "sink")
    monkeypatch.setattr(
        store,
        "ingest_provider_tickets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("secret")),
    )
    summary = _poller(store, _HaloPages([_response([_ticket("one")])])).poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "failed" and summary.reason == "ingest_invariant"


def test_remaining_sweep_boundaries_and_default_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, instance_id = _seed_store(tmp_path)
    monkeypatch.setattr(store, "get_connector_instance", lambda _instance_id: None)
    summary = _poller(store, _HaloPages([])).poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "failed" and summary.reason == "instance_missing"

    store, instance_id = _seed_store(tmp_path / "cap")
    summary = _poller(store, _HaloPages([_response([_ticket("one")], raw_count=1)])).poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "degraded" and summary.reason == "max_pages_exhausted"

    store, instance_id = _seed_store(tmp_path / "builder")
    sentinel = object()

    def build(_store: Store, _instance_id: str, **_kwargs: object) -> object:
        return sentinel

    monkeypatch.setattr(poller_module, "build_read_client_for", build)
    poller = IngestionPoller(
        store,
        base_settings=cast(Any, SimpleNamespace(connector_timeout_seconds=2.0)),
    )
    assert poller._build_client(instance_id) is sentinel


def test_internal_lease_and_cursor_reads_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, instance_id = _seed_store(tmp_path)
    poller = _poller(store, _HaloPages([]))
    monkeypatch.setattr(store, "get_sync_cursor", lambda *_args: (_ for _ in ()).throw(RuntimeError("secret")))
    assert poller._read_cursor(instance_id) is None

    assert store.claim_poll_lease(
        instance_id,
        "connector_poll",
        token="token",
        ttl_seconds=63,
        now=NOW,
    ) == PollLeaseClaimResult.GRANTED
    assert poller._holds_lease(instance_id, "wrong") is False
    with store._connect() as connection:
        connection.execute(
            "update sync_cursors set lease_expires_at = ? where connector_instance_id = ?",
            (NOW.replace("+00:00", ""), instance_id),
        )
    assert poller._holds_lease(instance_id, "token") is True
    monkeypatch.setattr(store, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("secret")))
    assert poller._holds_lease(instance_id, "token") is False


def test_invalid_retry_and_finish_paths_are_handled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, instance_id = _seed_store(tmp_path)
    poller = _poller(store, _HaloPages([]))
    class _ExpiredClock(_Clock):
        calls = 0

        def monotonic(self) -> float:
            self.calls += 1
            return 0.0 if self.calls == 1 else 2.0

    transient = _HaloPages([_response([], raw_count=0, http_status=503, retry_after=-1)])
    clipped = _poller(store, transient, _ExpiredClock())._fetch_with_retries(
        poller_module.ProviderTicketAdapter.for_connector("halopsa", instance_id),
        transient,
        page_number=1,
        page_size=1,
        started_at=0,
        deadline_seconds=1,
    )
    assert clipped.result == "invalid_retry_after"
    valid_transient = _HaloPages([_response([], raw_count=0, http_status=503, retry_after=0)])
    clipped = _poller(store, valid_transient, _ExpiredClock())._fetch_with_retries(
        poller_module.ProviderTicketAdapter.for_connector("halopsa", instance_id),
        valid_transient,
        page_number=1,
        page_size=1,
        started_at=0,
        deadline_seconds=1,
    )
    assert clipped.result == "deadline_exhausted"

    monkeypatch.setattr(
        store,
        "finish_poll_lease",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    finished = poller._finish(
        poller_module.PollSummary(instance_id, 0, 0, 0, "failed", "poll_error"),
        token="token",
        previous_cursor=None,
    )
    assert finished.reason == "lease_finish_error"


def test_more_bound_and_helper_validation_paths(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    with pytest.raises(ValueError, match="connector_timeout"):
        _poller(store, _HaloPages([]), connector_timeout_seconds=0).poll_instance(
            instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
        )
    with pytest.raises(ValueError, match="lease_ttl_seconds"):
        _poller(store, _HaloPages([])).poll_instance(
            instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=0
        )
    with pytest.raises(ValueError, match="connector_instance_id"):
        _poller(store, _HaloPages([])).poll_instance(
            " ", max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
        )

    assert poller_module._page_failure(
        poller_module.ProviderPage([], "ready", 0, -1, 200, None)
    ) == "malformed_response"
    assert poller_module._page_failure(
        poller_module.ProviderPage([], "ready", 0, 0, cast(Any, "200"), None)
    ) == "malformed_response"
    assert poller_module._exception_reason(HaloReadError("x")) == "provider_failure"
    try:
        raise HaloReadError("x") from httpx.ReadTimeout("timeout")
    except HaloReadError as error:
        assert poller_module._exception_reason(error) == "timeout"
    assert poller_module._cursor_page(cast(Any, type("Cursor", (), {"cursor_value": "0"})())) is None


def test_retry_exception_paths_are_bounded_and_deadline_clipped(tmp_path: Path) -> None:
    store, _ = _seed_store(tmp_path)
    poller = _poller(store, _HaloPages([]))
    adapter = _RaisingAdapter(httpx.ReadTimeout("timeout"))
    result = poller._fetch_with_retries(
        adapter,
        object(),
        page_number=1,
        page_size=1,
        started_at=0,
        deadline_seconds=10,
    )
    assert result.result == "timeout" and adapter.calls == 4

    clipped = _poller(store, _HaloPages([]), _Clock(monotonic_value=2.0))._fetch_with_retries(
        _RaisingAdapter(httpx.ReadTimeout("timeout")),
        object(),
        page_number=1,
        page_size=1,
        started_at=0,
        deadline_seconds=1,
    )
    assert clipped.result == "deadline_exhausted"


def test_private_taxonomy_and_clock_helpers() -> None:
    page = poller_module.ProviderPage([], "ready", 0, 0, 200, None)
    assert poller_module._page_failure(page) is None
    assert poller_module._page_failure(poller_module.ProviderPage([], "ready", 0, 0, 302, None)) == "provider_failure"
    assert poller_module._page_failure(
        poller_module.ProviderPage([], "configured", 0, 0, 200, None)
    ) == "malformed_response"
    assert poller_module._page_failure(
        poller_module.ProviderPage([], "ready", -1, 0, 200, None)
    ) == "malformed_response"
    assert poller_module._page_failure(
        poller_module.ProviderPage([], "ready", 0, 0, 200, float("nan"))
    ) == "invalid_retry_after"
    assert poller_module._transient_page(poller_module.ProviderPage([], "blocked", 0, 0, None, None))
    assert poller_module._exception_reason(HaloReadError("x", http_status=408)) == "request_timeout"
    assert poller_module._exception_reason(ConnectWiseReadError("x", http_status=429)) == "rate_limited"
    assert poller_module._exception_reason(HaloReadError("x", http_status=503)) == "provider_5xx"
    assert poller_module._exception_reason(httpx.ConnectError("x")) == "connect_fail"
    assert poller_module._exception_reason(ConnectorFactoryError("x")) == "factory_error"
    assert poller_module._exception_reason(ValueError("x")) == "provider_failure"
    assert poller_module._retry_after_value(120.0) == 60.0
    assert poller_module._retry_after_value(-1.0) is poller_module._INVALID_RETRY_AFTER
    assert poller_module._valid_retry_after(True) is False
    assert poller_module._finite_positive(1.0) and not poller_module._finite_positive(False)
    assert poller_module._finite_positive_bounded(1.0, 1.0)
    assert poller_module._cursor_page(None) is None
    assert poller_module._cursor_page(cast(Any, type("Cursor", (), {"cursor_value": "bad"})())) is None


def test_datetime_clock_and_default_timeout_paths(tmp_path: Path) -> None:
    store, _ = _seed_store(tmp_path)
    poller = IngestionPoller(store, client_builder=lambda *_args: object())
    assert poller.connector_timeout_seconds == 20.0
    naive = IngestionPoller(
        store,
        client_builder=lambda *_args: object(),
        wall_clock=lambda: datetime(2026, 8, 16, 12, 0, 0),
    )
    assert naive._now_text().endswith("+00:00")
    aware = IngestionPoller(
        store,
        client_builder=lambda *_args: object(),
        wall_clock=lambda: datetime.now().astimezone(),
    )
    assert "T" in aware._now_text()


def test_finish_and_audit_failures_are_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, instance_id = _seed_store(tmp_path)
    poller = _poller(store, _HaloPages([]))
    monkeypatch.setattr(store, "finish_poll_lease", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        store,
        "add_audit_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    summary = poller.poll_instance(
        instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=63
    )
    assert summary.status == "degraded" and summary.reason == "lease_lost"


def test_bounds_and_lease_ttl_are_rejected(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    poller = _poller(store, _HaloPages([_response([], raw_count=0)]))
    with pytest.raises(ValueError, match="max_pages"):
        poller.poll_instance(instance_id, max_pages=1001, page_size=1, deadline_seconds=1, lease_ttl_seconds=63)
    with pytest.raises(ValueError, match="page_size"):
        poller.poll_instance(instance_id, max_pages=1, page_size=101, deadline_seconds=1, lease_ttl_seconds=63)
    with pytest.raises(ValueError, match="deadline_seconds"):
        poller.poll_instance(instance_id, max_pages=1, page_size=1, deadline_seconds=3601, lease_ttl_seconds=63)
    with pytest.raises(ValueError, match="safety window"):
        poller.poll_instance(instance_id, max_pages=1, page_size=1, deadline_seconds=1, lease_ttl_seconds=62)


def test_fencing_aborts_before_the_next_page_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base, instance_id = _seed_store(tmp_path)
    original_ingest = base.ingest_provider_tickets
    writes = 0

    def ingest(records: list[Ticket], *, connector_instance_id: str) -> IngestSummary:
        nonlocal writes
        writes += 1
        result = original_ingest(records, connector_instance_id=connector_instance_id)
        with base._connect() as connection:
            connection.execute(
                "update sync_cursors set lease_expires_at = ? where connector_instance_id = ?",
                ((datetime.fromisoformat(NOW) - timedelta(seconds=1)).isoformat(), connector_instance_id),
            )
        return result

    monkeypatch.setattr(base, "ingest_provider_tickets", ingest)
    client = _HaloPages([_response([_ticket("one")]), _response([_ticket("two")])])
    summary = _poller(base, client).poll_instance(
        instance_id, max_pages=3, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )
    assert summary.status == "degraded"
    assert summary.reason == "lease_lost"
    assert writes == 1
    assert len(base.list_tickets("client-a")) == 1


def test_sink_audit_does_not_contain_provider_subject(tmp_path: Path) -> None:
    store, instance_id = _seed_store(tmp_path)
    secret_subject = "SECRET-CUSTOMER-DATA"
    client = _HaloPages(
        [
            _response([HaloTicket("one", secret_subject, "Open", "High", "company-a", "Acme")]),
            _response([], raw_count=0),
        ]
    )
    summary = _poller(store, client).poll_instance(
        instance_id, max_pages=5, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )
    assert summary.status == "idle"
    details = [event.detail for event in store.list_audit_events()]
    assert any("Imported provider ticket" in detail for detail in details)
    assert all(secret_subject not in detail for detail in details)


def test_poll_failure_logs_stable_redacted_fields(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store, instance_id = _seed_store(tmp_path)
    caplog.set_level("WARNING", logger=poller_module.__name__)
    poller = _poller(
        store,
        _HaloPages([]),
        client_builder=lambda *_args: (_ for _ in ()).throw(RuntimeError("provider secret should not be logged")),
    )
    summary = poller.poll_instance(
        instance_id, max_pages=1, page_size=25, deadline_seconds=10, lease_ttl_seconds=100
    )

    assert summary.status == "failed"
    assert summary.reason == "factory_error"
    record = next(record for record in caplog.records if record.message == "ingestion_poll_failed")
    assert getattr(record, "connector_instance_id", None) == instance_id
    assert getattr(record, "reason", None) == "factory_error"
    assert "provider secret" not in caplog.text
