"""Bounded, synchronous provider-ticket ingestion polling."""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx

from wait_local_agent.config import Settings, load_settings
from wait_local_agent.connector_factory import (
    ConnectorFactoryError,
    build_read_client_for,
)
from wait_local_agent.connectwise import ConnectWiseReadError
from wait_local_agent.halopsa import HaloReadError
from wait_local_agent.models import SyncCursor, utc_now
from wait_local_agent.provider_adapters import (
    ProviderPage,
    ProviderTicketAdapter,
    TicketListClient,
)
from wait_local_agent.store import PollLeaseClaimResult, Store

MAX_PAGES = 1000
MAX_PAGE_SIZE = 100
MAX_DEADLINE_SECONDS = 3600.0
MAX_PAGE_RETRIES = 3
MAX_BACKOFF_SECONDS = 60.0
DEFAULT_CONNECTOR_TIMEOUT_SECONDS = 20.0
POLL_CURSOR_TYPE = "connector_poll"

PollStatus = Literal["idle", "degraded", "failed", "skipped_locked"]


@dataclass(frozen=True)
class PollSummary:
    connector_instance_id: str
    pages_fetched: int
    written: int
    quarantined: int
    status: PollStatus
    reason: str


@dataclass(frozen=True)
class _FetchOutcome:
    result: ProviderPage | str
    transient_seen: bool


ClientBuilder = Callable[[Store, str], object]
Clock = Callable[[], object]


class IngestionPoller:
    """Poll one connector instance with bounded retries and a fenced lease."""

    def __init__(
        self,
        store: Store,
        *,
        client_builder: ClientBuilder | None = None,
        base_settings: Settings | None = None,
        vault: object | None = None,
        resolver: object | None = None,
        connector_timeout_seconds: float | None = None,
        wall_clock: Clock = utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.client_builder = client_builder or cast(ClientBuilder, build_read_client_for)
        self.base_settings = base_settings
        self.vault = vault
        self.resolver = resolver
        if connector_timeout_seconds is not None:
            self.connector_timeout_seconds = connector_timeout_seconds
        elif base_settings is not None:
            self.connector_timeout_seconds = base_settings.connector_timeout_seconds
        else:
            self.connector_timeout_seconds = DEFAULT_CONNECTOR_TIMEOUT_SECONDS
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock
        self.sleeper = sleeper

    def poll_instance(
        self,
        connector_instance_id: str,
        *,
        max_pages: int,
        page_size: int,
        deadline_seconds: float,
        lease_ttl_seconds: float,
    ) -> PollSummary:
        """Poll an instance and return a terminal summary; provider failures do not raise."""

        self._validate_bounds(
            max_pages=max_pages,
            page_size=page_size,
            deadline_seconds=deadline_seconds,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        normalized_instance_id = connector_instance_id.strip()
        if not normalized_instance_id:
            raise ValueError("connector_instance_id must be non-empty")

        started_at = self.monotonic_clock()
        token = uuid.uuid4().hex
        claimed = False
        previous_cursor = self._read_cursor(normalized_instance_id)
        summary = PollSummary(normalized_instance_id, 0, 0, 0, "failed", "poll_error")
        try:
            claim = self.store.claim_poll_lease(
                normalized_instance_id,
                POLL_CURSOR_TYPE,
                token=token,
                ttl_seconds=lease_ttl_seconds,
                now=self._now_text(),
            )
            if claim == PollLeaseClaimResult.LOCKED:
                summary = replace(summary, status="skipped_locked", reason="lease_locked")
            elif claim == PollLeaseClaimResult.INSTANCE_MISSING:
                summary = replace(summary, status="failed", reason="instance_missing")
            else:
                claimed = True
                summary = self._sweep(
                    normalized_instance_id,
                    token=token,
                    started_at=started_at,
                    max_pages=max_pages,
                    page_size=page_size,
                    deadline_seconds=deadline_seconds,
                    previous_cursor=previous_cursor,
                )
        except Exception:
            # Provider, factory, and store boundary failures are deliberately
            # reduced to a stable reason; exception text never reaches audit.
            summary = replace(summary, status="failed", reason="poll_error")
        finally:
            if claimed:
                summary = self._finish(summary, token=token, previous_cursor=previous_cursor)
            self._audit(normalized_instance_id, summary)
        return summary

    def _sweep(
        self,
        connector_instance_id: str,
        *,
        token: str,
        started_at: float,
        max_pages: int,
        page_size: int,
        deadline_seconds: float,
        previous_cursor: SyncCursor | None,
    ) -> PollSummary:
        instance = self.store.get_connector_instance(connector_instance_id)
        if instance is None:
            return PollSummary(connector_instance_id, 0, 0, 0, "failed", "instance_missing")
        if instance.status.strip().lower() != "active":
            return PollSummary(connector_instance_id, 0, 0, 0, "failed", "inactive_instance")

        try:
            adapter = ProviderTicketAdapter.for_connector(
                instance.connector_type,
                connector_instance_id,
            )
        except Exception:
            return PollSummary(connector_instance_id, 0, 0, 0, "failed", "unsupported_connector")

        try:
            client = self._build_client(connector_instance_id)
        except Exception:
            return PollSummary(connector_instance_id, 0, 0, 0, "failed", "factory_error")

        pages_fetched = 0
        written = 0
        quarantined = 0
        degraded_reason: str | None = None
        for page_number in range(1, max_pages + 1):
            if self._remaining(started_at, deadline_seconds) <= 0:
                return PollSummary(
                    connector_instance_id, pages_fetched, written, quarantined, "degraded", "deadline_exhausted"
                )
            pages_fetched += 1
            fetched = self._fetch_with_retries(
                adapter,
                client,
                page_number=page_number,
                page_size=page_size,
                started_at=started_at,
                deadline_seconds=deadline_seconds,
            )
            if isinstance(fetched.result, str):
                status: PollStatus = (
                    "degraded" if fetched.result in _DEGRADED_FETCH_REASONS else "failed"
                )
                return PollSummary(
                    connector_instance_id,
                    pages_fetched,
                    written,
                    quarantined,
                    status,
                    fetched.result,
                )
            page = fetched.result
            failure = _page_failure(page)
            if failure is not None:
                status = "degraded" if failure in _DEGRADED_PAGE_REASONS else "failed"
                return PollSummary(connector_instance_id, pages_fetched, written, quarantined, status, failure)

            if page.dropped_count:
                degraded_reason = "dropped_rows"
            elif fetched.transient_seen:
                degraded_reason = "transient_provider"
            # A page containing provider rows is not EOF even if normalization
            # dropped every row. Only a valid, empty, successful response ends
            # the sweep.
            if page.raw_count == 0:
                reason = degraded_reason or "empty_page"
                status = "degraded" if degraded_reason else "idle"
                return PollSummary(connector_instance_id, pages_fetched, written, quarantined, status, reason)

            if page.records:
                if not self._holds_lease(connector_instance_id, token):
                    return PollSummary(
                        connector_instance_id, pages_fetched, written, quarantined, "degraded", "lease_lost"
                    )
                try:
                    ingest = self.store.ingest_provider_tickets(
                        page.records,
                        connector_instance_id=connector_instance_id,
                    )
                except Exception:
                    return PollSummary(
                        connector_instance_id,
                        pages_fetched,
                        written,
                        quarantined,
                        "failed",
                        "ingest_invariant",
                    )
                written += ingest.written
                quarantined += ingest.quarantined

        return PollSummary(
            connector_instance_id,
            pages_fetched,
            written,
            quarantined,
            "degraded",
            "max_pages_exhausted",
        )

    def _fetch_with_retries(
        self,
        adapter: ProviderTicketAdapter,
        client: object,
        *,
        page_number: int,
        page_size: int,
        started_at: float,
        deadline_seconds: float,
    ) -> _FetchOutcome:
        transient_seen = False
        for attempt in range(MAX_PAGE_RETRIES + 1):
            try:
                page = adapter.fetch_page(cast(TicketListClient, client), page=page_number, page_size=page_size)
            except Exception as exc:
                reason = _exception_reason(exc)
                if reason in _RETRYABLE_EXCEPTION_REASONS and attempt < MAX_PAGE_RETRIES:
                    if not self._sleep_for_retry(
                        started_at,
                        deadline_seconds,
                        attempt=attempt,
                        retry_after=None,
                    ):
                        return _FetchOutcome("deadline_exhausted", transient_seen)
                    transient_seen = True
                    continue
                return _FetchOutcome(reason, transient_seen)

            transient = _transient_page(page)
            if transient and attempt < MAX_PAGE_RETRIES:
                transient_seen = True
                retry_after = _retry_after_value(page.retry_after)
                if retry_after is _INVALID_RETRY_AFTER:
                    return _FetchOutcome("invalid_retry_after", transient_seen)
                if not self._sleep_for_retry(
                    started_at,
                    deadline_seconds,
                    attempt=attempt,
                    retry_after=cast(float | None, retry_after),
                ):
                    return _FetchOutcome("deadline_exhausted", transient_seen)
                continue
            return _FetchOutcome(page, transient_seen)
        return _FetchOutcome("provider_failure", transient_seen)  # pragma: no cover

    def _sleep_for_retry(
        self,
        started_at: float,
        deadline_seconds: float,
        *,
        attempt: int,
        retry_after: float | None,
    ) -> bool:
        remaining = self._remaining(started_at, deadline_seconds)
        if remaining <= 0:
            return False
        backoff = min(2.0**attempt, MAX_BACKOFF_SECONDS)
        delay = min(max(backoff, retry_after or 0.0), MAX_BACKOFF_SECONDS, remaining)
        self.sleeper(delay)
        return self._remaining(started_at, deadline_seconds) > 0

    def _build_client(self, connector_instance_id: str) -> object:
        if self.client_builder is cast(ClientBuilder, build_read_client_for):
            settings = self.base_settings or load_settings()
            return build_read_client_for(
                self.store,
                connector_instance_id,
                base_settings=settings,
                vault=cast(Any, self.vault),
                resolver=cast(Any, self.resolver),
            )
        return self.client_builder(self.store, connector_instance_id)

    def _finish(
        self,
        summary: PollSummary,
        *,
        token: str,
        previous_cursor: SyncCursor | None,
    ) -> PollSummary:
        last_synced_at = self._now_text() if summary.status == "idle" else _last_synced(previous_cursor)
        try:
            finished = self.store.finish_poll_lease(
                summary.connector_instance_id,
                POLL_CURSOR_TYPE,
                token=token,
                status=cast(Literal["idle", "degraded", "failed"], summary.status),
                cursor_value=str(summary.pages_fetched) if summary.pages_fetched else _cursor_value(previous_cursor),
                last_synced_at=last_synced_at,
                now=self._now_text(),
            )
        except Exception:
            return replace(summary, status="failed", reason="lease_finish_error")
        if not finished:
            try:
                if self.store.get_connector_instance(summary.connector_instance_id) is None:
                    return summary
            except Exception:
                return replace(summary, status="degraded", reason="lease_lost")
            return replace(summary, status="degraded", reason="lease_lost")
        return summary

    def _audit(self, connector_instance_id: str, summary: PollSummary) -> None:
        try:
            self.store.add_audit_event(
                "ingestion.poll.completed",
                connector_instance_id,
                f"Ingestion poll {summary.status}: {summary.reason}",
            )
        except Exception:
            return

    def _read_cursor(self, connector_instance_id: str) -> SyncCursor | None:
        try:
            return self.store.get_sync_cursor(connector_instance_id, POLL_CURSOR_TYPE)
        except Exception:
            return None

    def _holds_lease(self, connector_instance_id: str, token: str) -> bool:
        """Read the internal lease columns immediately before a page write."""

        try:
            with self.store._connect() as connection:  # noqa: SLF001 - intentional fence read
                row = connection.execute(
                    """
                    select status, lease_token, lease_expires_at
                    from sync_cursors
                    where connector_instance_id = ? and cursor_type = ?
                    """,
                    (connector_instance_id, POLL_CURSOR_TYPE),
                ).fetchone()
            if row is None or str(row["status"]) != "syncing" or str(row["lease_token"]) != token:
                return False
            expires_at = datetime.fromisoformat(str(row["lease_expires_at"]))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            return expires_at >= datetime.fromisoformat(self._now_text())
        except Exception:
            return False

    def _remaining(self, started_at: float, deadline_seconds: float) -> float:
        return deadline_seconds - (self.monotonic_clock() - started_at)

    def _now_text(self) -> str:
        value = self.wall_clock()
        if isinstance(value, datetime):
            timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            return timestamp.astimezone(UTC).isoformat()
        return str(value)

    def _validate_bounds(
        self,
        *,
        max_pages: int,
        page_size: int,
        deadline_seconds: float,
        lease_ttl_seconds: float,
    ) -> None:
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= MAX_PAGES:
            raise ValueError("max_pages must be between 1 and 1000")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError("page_size must be between 1 and 100")
        if not _finite_positive_bounded(deadline_seconds, MAX_DEADLINE_SECONDS):
            raise ValueError("deadline_seconds must be finite, positive, and at most 3600")
        if not _finite_positive_bounded(self.connector_timeout_seconds, MAX_DEADLINE_SECONDS):
            raise ValueError("connector_timeout_seconds must be finite and positive")
        if not _finite_positive(lease_ttl_seconds):
            raise ValueError("lease_ttl_seconds must be finite and positive")
        required = deadline_seconds + 2 * self.connector_timeout_seconds + MAX_BACKOFF_SECONDS
        if lease_ttl_seconds < required:
            raise ValueError("lease_ttl_seconds is shorter than the poll safety window")


_INVALID_RETRY_AFTER = object()
_DEGRADED_FETCH_REASONS = frozenset(
    {"blocked", "rate_limited", "timeout", "connect_fail", "request_timeout", "provider_5xx"}
)
_DEGRADED_PAGE_REASONS = frozenset({"blocked", "rate_limited", "request_timeout", "provider_5xx"})
_RETRYABLE_EXCEPTION_REASONS = frozenset({"timeout", "connect_fail", "request_timeout", "provider_5xx", "rate_limited"})


def _page_failure(page: ProviderPage) -> str | None:
    if not _valid_retry_after(page.retry_after):
        return "invalid_retry_after"
    if not isinstance(page.raw_count, int) or isinstance(page.raw_count, bool) or page.raw_count < 0:
        return "malformed_response"
    if not isinstance(page.dropped_count, int) or isinstance(page.dropped_count, bool) or page.dropped_count < 0:
        return "malformed_response"
    status = page.provider_status.strip().casefold()
    http_status = page.http_status
    if http_status is not None and (not isinstance(http_status, int) or isinstance(http_status, bool)):
        return "malformed_response"
    if status == "blocked":
        return "blocked"
    if http_status in {408, 429}:
        return "request_timeout" if http_status == 408 else "rate_limited"
    if http_status is not None and 500 <= http_status <= 599:
        return "provider_5xx"
    if status != "ready":
        return "malformed_response" if status in {"configured", "not_configured"} else "provider_failure"
    if http_status is None or not 200 <= http_status <= 299:
        return "provider_failure"
    return None


def _transient_page(page: ProviderPage) -> bool:
    status = page.provider_status.strip().casefold()
    return status == "blocked" or page.http_status in {408, 429} or (
        page.http_status is not None and 500 <= page.http_status <= 599
    )


def _exception_reason(exc: Exception) -> str:
    status = getattr(exc, "http_status", None)
    if status == 408:
        return "request_timeout"
    if status == 429:
        return "rate_limited"
    if isinstance(status, int) and 500 <= status <= 599:
        return "provider_5xx"
    causes: list[BaseException] = [exc]
    if exc.__cause__ is not None:
        causes.append(exc.__cause__)
    if any(isinstance(item, httpx.TimeoutException) for item in causes):
        return "timeout"
    if any(isinstance(item, httpx.ConnectError) for item in causes):
        return "connect_fail"
    if isinstance(exc, (HaloReadError, ConnectWiseReadError)):
        return "provider_failure"
    if isinstance(exc, ConnectorFactoryError):
        return "factory_error"
    return "provider_failure"


def _retry_after_value(value: float | None) -> float | None | object:
    if value is None:
        return None
    if not _valid_retry_after(value):
        return _INVALID_RETRY_AFTER
    return min(value, MAX_BACKOFF_SECONDS)


def _valid_retry_after(value: object) -> bool:
    return value is None or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _finite_positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _finite_positive_bounded(value: object, maximum: float) -> bool:
    return _finite_positive(value) and cast(float, value) <= maximum


def _cursor_page(cursor: SyncCursor | None) -> int | None:
    if cursor is None or cursor.cursor_value is None:
        return None
    try:
        value = int(cursor.cursor_value)
    except ValueError:
        return None
    return value if value > 0 else None


def _cursor_value(cursor: SyncCursor | None) -> str | None:
    return cursor.cursor_value if cursor is not None else None


def _last_synced(cursor: SyncCursor | None) -> str | None:
    return cursor.last_synced_at if cursor is not None else None


__all__ = ["IngestionPoller", "PollSummary"]
