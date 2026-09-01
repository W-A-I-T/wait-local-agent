from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter

from wait_local_agent.client_scope import AllClients
from wait_local_agent.config import Settings
from wait_local_agent.rbac import AuthContext, Role, require_role, resolve_auth_context
from wait_local_agent.sessions import (
    CSRF_HEADER,
    SESSION_COOKIE_NAME,
    generate_session_token,
    hash_session_token,
    session_expiries,
)
from wait_local_agent.store import PrincipalDetails, Store, hash_credential

AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]
_CLIENT_ROLES = Literal["end_user", "viewer", "technician", "admin"]


class PrincipalCreateRequest(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    kind: Literal["customer", "staff"] = "staff"
    display_name: str = Field(min_length=1, max_length=256)

    model_config = ConfigDict(extra="forbid")


class PrincipalPatchRequest(BaseModel):
    active: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=256)

    model_config = ConfigDict(extra="forbid")


class CredentialRevokeRequest(BaseModel):
    credential_hash: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")


class ClientRoleRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    role: _CLIENT_ROLES

    model_config = ConfigDict(extra="forbid")


class GlobalRoleRequest(BaseModel):
    role: Literal["msp_admin"] = "msp_admin"

    model_config = ConfigDict(extra="forbid")


class LocalLoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)

    model_config = ConfigDict(extra="forbid")


def create_auth_router(limiter: Limiter | None = None) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["authentication principals"])
    limit_login: Callable[[Callable[..., object]], Callable[..., object]] = (
        limiter.limit("10/minute") if limiter is not None else (lambda endpoint: endpoint)
    )

    @router.get("/session")
    def session_probe(request: Request) -> dict[str, object]:
        store = _store(request)
        try:
            context = resolve_auth_context(
                request.app.state.settings,
                request.headers.get("authorization"),
                store,
                session_token=request.cookies.get(SESSION_COOKIE_NAME),
                request_method=request.method,
                csrf_header_present=CSRF_HEADER in request.headers,
            )
        except HTTPException:
            return {"authenticated": False}
        expires_at = None
        if context.session_token_hash:
            session = store.get_auth_session(context.session_token_hash)
            expires_at = session.absolute_expires_at if session is not None else None
        return {
            "authenticated": True,
            **_auth_view(context, settings=request.app.state.settings, expires_at=expires_at),
        }

    @router.post("/login/local")
    @limit_login
    def login_local(payload: LocalLoginRequest, request: Request, response: Response) -> dict[str, object]:
        store = _store(request)
        settings = request.app.state.settings
        try:
            context = resolve_auth_context(settings, f"Bearer {payload.token}", store)
        except HTTPException as exc:
            raise HTTPException(status_code=401, detail="invalid credentials") from exc

        # Only credentials persisted for an active DB principal can mint a
        # session. Environment bootstrap and end-user tokens remain bearer-only.
        principal = store.find_principal_by_credential_hash(hash_credential(payload.token))
        if principal is None or context.principal_id is None:
            return {"session_created": False}

        session_token = generate_session_token()
        session_token_hash = hash_session_token(session_token)
        idle_expires_at, absolute_expires_at = session_expiries(
            idle_ttl_minutes=settings.session_idle_ttl_minutes,
            absolute_ttl_minutes=settings.session_absolute_ttl_minutes,
        )
        store.create_auth_session(
            session_token_hash,
            principal.principal_id,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            auth_method="local",
            user_agent=request.headers.get("user-agent", ""),
        )
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_token,
            max_age=settings.session_absolute_ttl_minutes * 60,
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return {
            "session_created": True,
            **_auth_view(
                context,
                settings=settings,
                auth_method="local",
                expires_at=absolute_expires_at,
            ),
        }

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict[str, object]:
        cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
        if cookie_token and request.headers.get("authorization") is None:
            # Resolve first so a valid cookie logout is CSRF-protected. Invalid
            # or already-expired cookies are still safely cleared below.
            try:
                context = resolve_auth_context(
                    request.app.state.settings,
                    None,
                    _store(request),
                    session_token=cookie_token,
                    request_method=request.method,
                    csrf_header_present=CSRF_HEADER in request.headers,
                )
            except HTTPException as exc:
                if exc.status_code == 403:
                    raise
                context = None
            if context is not None and context.session_token_hash:
                _store(request).revoke_auth_session(context.session_token_hash)
        elif cookie_token:
            _store(request).revoke_auth_session(hash_session_token(cookie_token))
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/",
            secure=request.app.state.settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return {"authenticated": False}

    @router.get("/principals")
    def list_principals(request: Request, context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        store = _store(request)
        return [_principal_view(store, principal) for principal in store.list_principals_with_details()]

    @router.post("/principals")
    def create_principal(
        payload: PrincipalCreateRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        store = _store(request)
        try:
            principal_id = store.create_principal(
                payload.principal_id,
                kind=payload.kind,
                display_name=payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="principal already exists") from exc
        store.add_audit_event("principal.created", principal_id, "succeeded", approver_id=_actor_id(context))
        return _principal_view_by_id(store, principal_id)

    @router.patch("/principals/{principal_id}")
    def update_principal(
        principal_id: str,
        payload: PrincipalPatchRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        if payload.active is None and payload.display_name is None:
            raise HTTPException(status_code=422, detail="active or display_name is required")
        if not normalized_id:
            raise HTTPException(status_code=404, detail="principal not found")
        if payload.active is False and context.principal_id == normalized_id:
            raise HTTPException(status_code=409, detail="you cannot deactivate your own principal")
        store = _store(request)
        try:
            if payload.active is not None:
                store.set_principal_active(normalized_id, payload.active)
                if payload.active is False:
                    store.revoke_principal_sessions(normalized_id)
            if payload.display_name is not None:
                store.set_principal_display_name(normalized_id, payload.display_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="principal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.add_audit_event("principal.updated", normalized_id, "succeeded", approver_id=_actor_id(context))
        return _principal_view_by_id(store, normalized_id)

    @router.post("/principals/{principal_id}/credentials")
    def issue_credential(
        principal_id: str,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        store = _store(request)
        principal = _find_principal(store, principal_id)
        if principal is None:
            raise HTTPException(status_code=404, detail="principal not found")
        if not principal.active:
            raise HTTPException(status_code=409, detail="credentials require an active principal")
        token = secrets.token_urlsafe(32)
        credential_hash = store.add_principal_credential(principal.principal_id, token)
        store.add_audit_event(
            "principal.credential.issued",
            principal.principal_id,
            "succeeded",
            approver_id=_actor_id(context),
        )
        return {
            "principal_id": principal.principal_id,
            "token": token,
            "credential_hash": credential_hash,
            "created_at": _credential_created_at(store, principal.principal_id, credential_hash),
        }

    @router.post("/principals/{principal_id}/credentials/revoke")
    def revoke_credential(
        principal_id: str,
        payload: CredentialRevokeRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        store = _store(request)
        principal = _find_principal(store, normalized_id)
        if principal is None:
            raise HTTPException(status_code=404, detail="principal not found")
        matched = _credential_belongs_to_principal(store, normalized_id, payload.credential_hash)
        if not matched:
            raise HTTPException(status_code=404, detail="credential not found")
        try:
            store.revoke_principal_credential(payload.credential_hash)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="credential not found") from exc
        store.add_audit_event(
            "principal.credential.revoked",
            normalized_id,
            "succeeded",
            approver_id=_actor_id(context),
        )
        return {"principal_id": normalized_id, "credential_hash_prefix": payload.credential_hash[:12], "active": False}

    @router.post("/principals/{principal_id}/client-roles")
    def add_client_role(
        principal_id: str,
        payload: ClientRoleRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        normalized_client_id = payload.client_id.strip()
        store = _store(request)
        if _find_principal(store, normalized_id) is None:
            raise HTTPException(status_code=404, detail="principal not found")
        if not normalized_client_id or normalized_client_id == "__quarantine__":
            raise HTTPException(status_code=404, detail="client not found")
        if store.get_client(AllClients(), normalized_client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            store.add_principal_client_role(normalized_id, normalized_client_id, payload.role)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="client role already exists") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.add_audit_event(
            "principal.client_role.added",
            f"{normalized_id}:{normalized_client_id}:{payload.role}",
            "succeeded",
            approver_id=_actor_id(context),
        )
        return _principal_view_by_id(store, normalized_id)

    @router.delete("/principals/{principal_id}/client-roles")
    def remove_client_role(
        principal_id: str,
        payload: ClientRoleRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        store = _store(request)
        if _find_principal(store, normalized_id) is None:
            raise HTTPException(status_code=404, detail="principal not found")
        try:
            store.remove_principal_client_role(normalized_id, payload.client_id, payload.role)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client role not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.add_audit_event(
            "principal.client_role.removed",
            f"{normalized_id}:{payload.client_id.strip()}:{payload.role}",
            "succeeded",
            approver_id=_actor_id(context),
        )
        return _principal_view_by_id(store, normalized_id)

    @router.post("/principals/{principal_id}/global-roles")
    def add_global_role(
        principal_id: str,
        payload: GlobalRoleRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        store = _store(request)
        if _find_principal(store, normalized_id) is None:
            raise HTTPException(status_code=404, detail="principal not found")
        try:
            store.add_principal_global_role(normalized_id, payload.role)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="global role already exists") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.add_audit_event(
            "principal.global_role.added",
            normalized_id,
            "succeeded",
            approver_id=_actor_id(context),
        )
        return _principal_view_by_id(store, normalized_id)

    @router.delete("/principals/{principal_id}/global-roles")
    def remove_global_role(
        principal_id: str,
        payload: GlobalRoleRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        if context.principal_id == normalized_id and payload.role == "msp_admin":
            raise HTTPException(status_code=409, detail="you cannot remove your own msp_admin role")
        store = _store(request)
        if _find_principal(store, normalized_id) is None:
            raise HTTPException(status_code=404, detail="principal not found")
        try:
            store.remove_principal_global_role(normalized_id, payload.role)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="global role not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.add_audit_event(
            "principal.global_role.removed",
            normalized_id,
            "succeeded",
            approver_id=_actor_id(context),
        )
        return _principal_view_by_id(store, normalized_id)

    return router


def _store(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if not isinstance(store, Store):
        raise HTTPException(status_code=503, detail="Local authorization store is unavailable.")
    return store


def _require_msp_operator(context: AuthContext) -> None:
    if not context.demo_mode and not context.is_msp_admin:
        raise HTTPException(status_code=403, detail="msp operator access required")


def _require_live_management(context: AuthContext) -> None:
    if context.demo_mode:
        raise HTTPException(status_code=403, detail="principal management cannot be changed in demo mode")


def _require_management_access(context: AuthContext) -> None:
    _require_msp_operator(context)
    _require_live_management(context)


def _actor_id(context: AuthContext) -> str:
    return context.principal_id or context.approver_id or "bootstrap-admin"


def _auth_view(
    context: AuthContext,
    *,
    settings: Settings,
    auth_method: str | None = None,
    expires_at: str | None = None,
) -> dict[str, object]:
    return {
        "role": context.role.label(),
        "client_id": context.client_id,
        "client_ids": sorted(context.client_ids),
        "principal_id": context.principal_id,
        "is_msp_admin": context.is_msp_admin,
        "auth_method": auth_method or context.auth_method,
        "expires_at": expires_at,
        "api_auth_required": not settings.demo_mode,
        "demo_mode": settings.demo_mode,
        "end_user_support_enabled": settings.end_user_support_enabled,
    }


def _find_principal(store: Store, principal_id: str) -> PrincipalDetails | None:
    normalized_id = principal_id.strip()
    return next(
        (principal for principal in store.list_principals_with_details() if principal.principal_id == normalized_id),
        None,
    )


def _principal_view(store: Store, principal: PrincipalDetails) -> dict[str, object]:
    return {
        "principal_id": principal.principal_id,
        "kind": principal.principal_kind,
        "display_name": principal.display_name,
        "active": principal.active,
        "created_at": principal.created_at,
        "client_roles": principal.client_roles,
        "global_roles": principal.global_roles,
        "credential_count": principal.credential_count,
        "credentials": [asdict(credential) for credential in store.list_principal_credentials(principal.principal_id)],
    }


def _principal_view_by_id(store: Store, principal_id: str) -> dict[str, object]:
    principal = _find_principal(store, principal_id)
    if principal is None:
        raise HTTPException(status_code=404, detail="principal not found")
    return _principal_view(store, principal)


def _credential_belongs_to_principal(store: Store, principal_id: str, credential_hash: str) -> bool:
    prefix = credential_hash.strip()[:12]
    return any(
        credential.credential_hash_prefix == prefix
        for credential in store.list_principal_credentials(principal_id)
    )


def _credential_created_at(store: Store, principal_id: str, credential_hash: str) -> str:
    prefix = credential_hash[:12]
    for credential in store.list_principal_credentials(principal_id):
        if credential.credential_hash_prefix == prefix:
            return credential.created_at
    raise RuntimeError("credential was not persisted")
