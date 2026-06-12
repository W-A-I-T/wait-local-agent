from __future__ import annotations

from secrets import compare_digest

from fastapi import HTTPException, status

from wait_local_agent.config import Settings


def auth_required(settings: Settings) -> bool:
    """Return whether the API should require a bearer token."""

    return not settings.demo_mode and bool(settings.api_token)


def require_bearer_authorization(settings: Settings, authorization: str | None) -> None:
    """Validate an Authorization header against WAIT_API_TOKEN."""

    if not auth_required(settings):
        return
    if not authorization:
        raise _unauthorized("missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise _unauthorized("invalid bearer token")
    if not compare_digest(token, settings.api_token):
        raise _unauthorized("invalid bearer token")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
