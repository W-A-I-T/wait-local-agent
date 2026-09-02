from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from wait_local_agent.lp_client import (
    LaunchPassportError,
    LaunchPassportForbidden,
    LaunchPassportInsufficientCredits,
    LaunchPassportRateLimited,
    LaunchPassportUnauthorized,
)

PollStatus = Literal[
    "queued",
    "running",
    "retrying",
    "unknown",
    "completed",
    "failed",
    "canceled",
    "timed_out",
    "not_authorized",
    "unavailable",
]
TERMINAL_SCAN_STATES = frozenset({"completed", "failed", "canceled"})
ACTIVE_SCAN_STATES = frozenset({"queued", "running", "retrying", "unknown"})
POLL_TERMINAL_STATES = TERMINAL_SCAN_STATES | {"timed_out", "not_authorized", "unavailable"}


class ScanPollClient(Protocol):
    def get_scan(self, scan_id: str) -> dict[str, Any]: ...

    def latest_report(self, project_id: str) -> dict[str, Any] | list[Any]: ...


@dataclass(frozen=True)
class PollOutcome:
    status: PollStatus
    scan_id: str
    attempts: int
    elapsed_seconds: float
    scan: dict[str, Any] | None = None
    report: dict[str, Any] | list[Any] | None = None
    error: str | None = None
    retry_after: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scan_id": self.scan_id,
            "attempts": self.attempts,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "scan": self.scan,
            "report": self.report,
            "error": self.error,
            "retry_after": self.retry_after,
        }


def poll_scan(
    client: ScanPollClient,
    project_id: str,
    scan_id: str,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    initial_delay: float = 30.0,
    max_delay: float = 600.0,
    max_duration: float = 3600.0,
    max_attempts: int = 120,
) -> PollOutcome:
    """Poll one remote scan without allowing an unbounded wait or exception escape."""
    if not project_id.strip() or not scan_id.strip():
        raise ValueError("project id and scan id are required")
    if initial_delay <= 0 or max_delay <= 0 or max_duration <= 0 or max_attempts <= 0:
        raise ValueError("polling bounds must be positive")

    started = clock()
    delay = min(initial_delay, max_delay)
    attempts = 0
    last_error: str | None = None
    last_retry_after: float | None = None

    while attempts < max_attempts:
        elapsed = clock() - started
        remaining = max_duration - elapsed
        if remaining <= 0:
            return _timeout(scan_id, attempts, clock() - started)
        sleep(min(delay, remaining))
        elapsed = clock() - started
        if elapsed >= max_duration:
            return _timeout(scan_id, attempts, elapsed)

        outcome = poll_scan_once(
            client,
            project_id,
            scan_id,
            attempts=attempts,
            elapsed_seconds=clock() - started,
        )
        attempts = outcome.attempts
        if outcome.status in POLL_TERMINAL_STATES:
            return _outcome(
                outcome.status,
                scan_id,
                attempts,
                clock() - started,
                scan=outcome.scan,
                report=outcome.report,
                error=outcome.error or last_error,
                retry_after=outcome.retry_after or last_retry_after,
            )
        if outcome.status == "retrying":
            last_error = outcome.error
            last_retry_after = outcome.retry_after
            delay = min(max(delay, outcome.retry_after or 0.0), max_delay)
            continue
        if outcome.status == "unknown":
            last_error = "Launch Passport returned an unknown scan state"
        delay = min(delay * 2, max_delay)

    return _timeout(scan_id, attempts, clock() - started, error=last_error, retry_after=last_retry_after)


def poll_scan_once(
    client: ScanPollClient,
    project_id: str,
    scan_id: str,
    *,
    attempts: int = 0,
    elapsed_seconds: float = 0.0,
) -> PollOutcome:
    """Advance one remote scan state without sleeping or looping.

    This is the scheduler-safe primitive.  Callers own persistence, retry
    timing, and the overall duration/attempt budget.
    """
    if not project_id.strip() or not scan_id.strip():
        raise ValueError("project id and scan id are required")
    if attempts < 0 or elapsed_seconds < 0:
        raise ValueError("polling progress must not be negative")

    next_attempt = attempts + 1
    try:
        scan = client.get_scan(scan_id)
    except LaunchPassportRateLimited as exc:
        return _outcome(
            "retrying",
            scan_id,
            next_attempt,
            elapsed_seconds,
            error="Launch Passport polling was rate limited",
            retry_after=exc.retry_after,
        )
    except (LaunchPassportUnauthorized, LaunchPassportForbidden):
        return _outcome(
            "not_authorized",
            scan_id,
            next_attempt,
            elapsed_seconds,
            error="scan polling is not authorized",
        )
    except LaunchPassportInsufficientCredits:
        return _outcome(
            "unavailable",
            scan_id,
            next_attempt,
            elapsed_seconds,
            error="Launch Passport credits are insufficient",
        )
    except LaunchPassportError:
        return _outcome(
            "unavailable",
            scan_id,
            next_attempt,
            elapsed_seconds,
            error="scan polling request failed",
        )
    except Exception:
        return _outcome("unavailable", scan_id, next_attempt, elapsed_seconds, error="scan polling failed")

    state = _scan_state(scan)
    if state in TERMINAL_SCAN_STATES:
        report: dict[str, Any] | list[Any] | None = None
        report_error: str | None = None
        if state == "completed":
            try:
                report = client.latest_report(project_id)
            except (LaunchPassportUnauthorized, LaunchPassportForbidden):
                report_error = "latest report is not authorized"
            except LaunchPassportError:
                report_error = "latest report request failed"
            except Exception:
                report_error = "latest report request failed"
        return _outcome(
            state,  # type: ignore[arg-type]
            scan_id,
            next_attempt,
            elapsed_seconds,
            scan=scan,
            report=report,
            error=report_error,
        )

    if state in ACTIVE_SCAN_STATES:
        return _outcome(state, scan_id, next_attempt, elapsed_seconds, scan=scan)  # type: ignore[arg-type]
    return _outcome(
        "unknown",
        scan_id,
        next_attempt,
        elapsed_seconds,
        scan=scan,
        error="Launch Passport returned an unknown scan state",
    )


def _scan_state(scan: dict[str, Any]) -> str:
    value = scan.get("status") or scan.get("state") or "unknown"
    return value.strip().lower() if isinstance(value, str) and value.strip() else "unknown"


def _outcome(
    status: PollStatus,
    scan_id: str,
    attempts: int,
    elapsed: float,
    *,
    scan: dict[str, Any] | None = None,
    report: dict[str, Any] | list[Any] | None = None,
    error: str | None = None,
    retry_after: float | None = None,
) -> PollOutcome:
    return PollOutcome(
        status=status,
        scan_id=scan_id,
        attempts=attempts,
        elapsed_seconds=max(0.0, elapsed),
        scan=scan,
        report=report,
        error=error,
        retry_after=retry_after,
    )


def _timeout(
    scan_id: str,
    attempts: int,
    elapsed: float,
    *,
    error: str | None = "scan polling timed out",
    retry_after: float | None = None,
) -> PollOutcome:
    return _outcome(
        "timed_out",
        scan_id,
        attempts,
        elapsed,
        error=error,
        retry_after=retry_after,
    )
