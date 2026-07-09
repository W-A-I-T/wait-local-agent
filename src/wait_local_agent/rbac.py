from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum
from secrets import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from wait_local_agent.config import Settings


class Role(IntEnum):
    VIEWER = 1
    TECHNICIAN = 2
    ADMIN = 3

    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class AuthContext:
    role: Role
    presented_token: str | None

    @property
    def approver_id(self) -> str | None:
        if not self.presented_token:
            return None
        return hashlib.sha256(self.presented_token.encode("utf-8")).hexdigest()[:16]


def tokens_configured(settings: Settings) -> bool:
    return bool(
        settings.api_token
        or settings.admin_token
        or settings.tech_token
        or settings.viewer_token
    )


def resolve_auth_context(settings: Settings, authorization: str | None) -> AuthContext:
    if not tokens_configured(settings) or settings.demo_mode:
        return AuthContext(role=Role.ADMIN, presented_token=None)

    token = _extract_bearer_token(authorization)
    for candidate, role in (
        (settings.api_token, Role.ADMIN),
        (settings.admin_token, Role.ADMIN),
        (settings.tech_token, Role.TECHNICIAN),
        (settings.viewer_token, Role.VIEWER),
    ):
        if candidate and compare_digest(token, candidate):
            return AuthContext(role=role, presented_token=token)
    raise _unauthorized("invalid bearer token")


def require_role(minimum: Role):
    def dependency(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> AuthContext:
        settings = request.app.state.settings
        context = resolve_auth_context(settings, authorization)
        if context.role < minimum:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return context

    return dependency


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _unauthorized("missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise _unauthorized("invalid bearer token")
    return token


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
