from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

SESSION_COOKIE_NAME = "wait_session"
CSRF_HEADER = "X-WAIT-CSRF"
DEFAULT_SESSION_IDLE_TTL_MINUTES = 12 * 60
DEFAULT_SESSION_ABSOLUTE_TTL_MINUTES = 7 * 24 * 60


def generate_session_token() -> str:
    """Generate a fresh opaque token for a server-side session."""

    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Return the persisted digest for an opaque session token."""

    if not isinstance(token, str) or not token:
        raise ValueError("session token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiries(
    *,
    now: datetime | None = None,
    idle_ttl_minutes: int = DEFAULT_SESSION_IDLE_TTL_MINUTES,
    absolute_ttl_minutes: int = DEFAULT_SESSION_ABSOLUTE_TTL_MINUTES,
) -> tuple[str, str]:
    """Return idle and absolute expiry timestamps in the store's ISO format."""

    if idle_ttl_minutes <= 0 or absolute_ttl_minutes <= 0:
        raise ValueError("session TTLs must be positive")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    absolute_expires_at = current + timedelta(minutes=absolute_ttl_minutes)
    idle_expires_at = min(current + timedelta(minutes=idle_ttl_minutes), absolute_expires_at)
    return idle_expires_at.isoformat(), absolute_expires_at.isoformat()
