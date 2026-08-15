from __future__ import annotations

from wait_local_agent.config import Settings
from wait_local_agent.rbac import resolve_auth_context


def auth_required(settings: Settings) -> bool:
    """Return whether the API should require a bearer token."""

    return not settings.demo_mode


def require_bearer_authorization(settings: Settings, authorization: str | None) -> None:
    """Validate an Authorization header against configured WAIT_* tokens."""

    resolve_auth_context(settings, authorization)
