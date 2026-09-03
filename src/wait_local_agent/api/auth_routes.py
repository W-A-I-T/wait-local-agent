from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter

from wait_local_agent.client_scope import AllClients
from wait_local_agent.config import Settings
from wait_local_agent.oidc import (
    OIDC_CLIENT_SECRET_KEY,
    OidcConfig,
    build_oauth_client,
    load_oidc_config,
    resolve_identity,
    validate_next_path,
)
from wait_local_agent.rbac import AuthContext, Role, require_role, resolve_auth_context
from wait_local_agent.sessions import (
    CSRF_HEADER,
    SESSION_COOKIE_NAME,
    generate_session_token,
    hash_session_token,
    session_expiries,
)
from wait_local_agent.store import PrincipalDetails, PrincipalInvariantError, Store, hash_credential
from wait_local_agent.vault import SecretVault, SecretVaultError

AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]
_CLIENT_ROLES = Literal["end_user", "viewer", "technician", "admin"]


class ClientRoleRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    role: _CLIENT_ROLES

    model_config = ConfigDict(extra="forbid")


class PrincipalCreateRequest(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    kind: Literal["customer", "staff"] = "staff"
    display_name: str = Field(min_length=1, max_length=256)
    client_roles: list[ClientRoleRequest] = Field(default_factory=list, max_length=50)
    msp_admin: bool = False
    issue_credential: bool = False

    model_config = ConfigDict(extra="forbid")


class PrincipalPatchRequest(BaseModel):
    active: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=256)

    model_config = ConfigDict(extra="forbid")


class CredentialRevokeRequest(BaseModel):
    credential_hash: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")


class GlobalRoleRequest(BaseModel):
    role: Literal["msp_admin"] = "msp_admin"

    model_config = ConfigDict(extra="forbid")


class LocalLoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)

    model_config = ConfigDict(extra="forbid")


class OidcConfigRequest(BaseModel):
    enabled: bool = False
    tenant_id: str = Field(default="", max_length=320)
    client_id: str = Field(default="", max_length=320)
    public_base_url: str = Field(default="", max_length=512)
    auto_provision_enabled: bool = False
    auto_provision_tenant_id: str = Field(default="", max_length=320)
    auto_provision_client_id: str = Field(default="", max_length=128)
    auto_provision_role: Literal["viewer"] = "viewer"
    client_secret: str = Field(default="", max_length=4096)

    model_config = ConfigDict(extra="forbid")


class PrincipalIdentityRequest(BaseModel):
    issuer: str | None = Field(default=None, max_length=512)
    subject: str = Field(min_length=1, max_length=512)
    subject_kind: Literal["oid", "email"]

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

        _, absolute_expires_at = _create_browser_session(
            store,
            settings,
            response,
            principal.principal_id,
            auth_method="local",
            user_agent=request.headers.get("user-agent", ""),
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

    @router.get("/oidc/status")
    @limit_login
    def oidc_status(request: Request) -> dict[str, bool]:
        config = _oidc_config(request)
        return {"enabled": config.enabled}

    @router.get("/oidc/login")
    @limit_login
    async def oidc_login(
        request: Request,
        next_path: str | None = Query(default=None, alias="next", max_length=4096),
    ) -> Response:
        config = _oidc_config(request)
        if not config.enabled:
            raise HTTPException(status_code=404, detail="OIDC sign-in is not enabled")
        try:
            validated_next = validate_next_path(next_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid next path") from exc
        request.session["oidc_next"] = validated_next
        try:
            client = build_oauth_client(config)
            return await client.authorize_redirect(request, config.redirect_uri)
        except Exception as exc:  # noqa: BLE001 - provider details must not reach logs or clients
            raise HTTPException(status_code=502, detail="Microsoft sign-in is unavailable") from exc

    @router.get("/oidc/callback")
    @limit_login
    async def oidc_callback(request: Request) -> Response:
        config = _oidc_config(request)
        if not config.enabled:
            raise HTTPException(status_code=404, detail="OIDC sign-in is not enabled")
        try:
            token = await build_oauth_client(config).authorize_access_token(request)
        except Exception as exc:  # noqa: BLE001 - Authlib/provider errors can contain token material
            if exc.__class__.__name__ == "MismatchingStateError":
                raise HTTPException(status_code=400, detail="invalid sign-in transaction") from exc
            raise HTTPException(status_code=400, detail="Microsoft sign-in could not be completed") from exc
        claims = token.get("userinfo") if isinstance(token, dict) else None
        if not isinstance(claims, dict):
            raise HTTPException(status_code=400, detail="Microsoft sign-in returned no identity")
        if claims.get("tid") != config.tenant_id or claims.get("iss") not in {None, config.issuer}:
            raise HTTPException(status_code=403, detail="Microsoft tenant is not allowed")
        principal_id = resolve_identity(_store(request), claims, config)
        if principal_id is None:
            return RedirectResponse(url="/#/login?error=not_provisioned", status_code=303)
        response = RedirectResponse(
            url=validate_next_path(request.session.pop("oidc_next", "/")),
            status_code=303,
        )
        _create_browser_session(
            _store(request),
            request.app.state.settings,
            response,
            principal_id,
            auth_method="oidc",
            user_agent=request.headers.get("user-agent", ""),
        )
        return response

    @router.get("/oidc/config")
    def get_oidc_config(request: Request, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        config = _oidc_config(request)
        return _oidc_config_view(config)

    @router.put("/oidc/config")
    def put_oidc_config(
        payload: OidcConfigRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        store = _store(request)
        settings = request.app.state.settings
        current = _oidc_config(request)
        secret = payload.client_secret.strip() or current.client_secret
        allowed_tenant = (payload.auto_provision_tenant_id.strip() or payload.tenant_id.strip())
        allowed_client = payload.auto_provision_client_id.strip() or settings.client_id.strip()
        candidate = OidcConfig(
            tenant_id=payload.tenant_id.strip(),
            client_id=payload.client_id.strip(),
            public_base_url=payload.public_base_url.strip().rstrip("/"),
            client_secret=secret,
            enabled=payload.enabled,
            auto_provision_enabled=payload.auto_provision_enabled,
            auto_provision_tenant_id=allowed_tenant,
            auto_provision_client_id=allowed_client,
        )
        if payload.enabled and (
            not candidate.complete
            or (payload.auto_provision_enabled and not allowed_tenant)
        ):
            raise HTTPException(status_code=422, detail="enabled OIDC configuration is incomplete")
        try:
            if payload.client_secret.strip():
                vault = _vault(request)
                if not vault.is_initialized():
                    vault = SecretVault.initialize(settings.vault_path, demo_mode=settings.demo_mode)
                    request.app.state.vault = vault
                vault.set(OIDC_CLIENT_SECRET_KEY, payload.client_secret.strip())
            actor_id = _actor_id(context)
            for key, value in (
                ("oidc.enabled", "true" if payload.enabled else "false"),
                ("oidc.tenant_id", candidate.tenant_id),
                ("oidc.client_id", candidate.client_id),
                ("oidc.public_base_url", candidate.public_base_url),
                ("oidc.auto_provision_enabled", "true" if payload.auto_provision_enabled else "false"),
                ("oidc.auto_provision_tenant_id", allowed_tenant),
                ("oidc.auto_provision_client_id", allowed_client),
                ("oidc.auto_provision_role", "viewer"),
            ):
                store.set_app_config(key, value, updated_by=actor_id)
        except (SecretVaultError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail="OIDC configuration could not be stored") from exc
        store.add_audit_event(
            "auth.oidc.config.updated", "oidc", "configuration updated", approver_id=_actor_id(context)
        )
        return _oidc_config_view(_oidc_config(request))

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
        token = secrets.token_urlsafe(32) if payload.issue_credential else None
        try:
            principal_id, issued_token = store.create_principal_with_access(
                payload.principal_id,
                kind=payload.kind,
                display_name=payload.display_name,
                client_roles=tuple((role.client_id, role.role) for role in payload.client_roles),
                msp_admin=payload.msp_admin,
                credential=token,
            )
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.created", payload.principal_id.strip(), str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="principal already exists") from exc
        store.add_audit_event("principal.created", principal_id, "succeeded", approver_id=_actor_id(context))
        result = _principal_view_by_id(store, principal_id)
        result["token"] = issued_token
        result["credential_notice"] = (
            "This credential is returned once. Store it securely; WAIT persists only its hash."
            if issued_token is not None
            else "No credential was issued."
        )
        return result

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
            if payload.active is False:
                store.deactivate_principal(
                    normalized_id,
                    actor_principal_id=context.principal_id,
                    audit_actor_id=_actor_id(context),
                )
            elif payload.active is True:
                store.set_principal_active(normalized_id, True)
            if payload.display_name is not None:
                store.set_principal_display_name(normalized_id, payload.display_name)
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.updated", normalized_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="principal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if payload.active is not False:
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
        token = secrets.token_urlsafe(32)
        try:
            credential_hash = store.add_principal_credential(principal.principal_id, token)
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.credential.issued", principal.principal_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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

    @router.post("/principals/{principal_id}/credentials/rotate")
    def rotate_credential(
        principal_id: str,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        store = _store(request)
        principal = _find_principal(store, normalized_id)
        if principal is None:
            raise HTTPException(status_code=404, detail="principal not found")
        token = secrets.token_urlsafe(32)
        try:
            credential_hash = store.rotate_principal_credential(normalized_id, token)
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.credential.rotated", normalized_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="principal not found") from exc
        store.add_audit_event(
            "principal.credential.rotated",
            normalized_id,
            "succeeded",
            approver_id=_actor_id(context),
        )
        return {
            "principal_id": normalized_id,
            "token": token,
            "credential_hash": credential_hash,
            "created_at": _credential_created_at(store, normalized_id, credential_hash),
        }

    @router.post("/principals/{principal_id}/credentials/revoke-all")
    def revoke_all_credentials(
        principal_id: str,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        normalized_id = principal_id.strip()
        store = _store(request)
        if _find_principal(store, normalized_id) is None:
            raise HTTPException(status_code=404, detail="principal not found")
        try:
            store.revoke_all_principal_credentials(
                normalized_id,
                actor_principal_id=context.principal_id,
            )
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.credentials.revoked", normalized_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="principal not found") from exc
        store.add_audit_event(
            "principal.credentials.revoked",
            normalized_id,
            "succeeded",
            approver_id=_actor_id(context),
        )
        return _principal_view_by_id(store, normalized_id)

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
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.credential.revoked", normalized_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        except PrincipalInvariantError as exc:
            subject_id = f"{normalized_id}:{normalized_client_id}:{payload.role}"
            _audit_principal_rejection(store, "principal.client_role.added", subject_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
            store.remove_principal_client_role(
                normalized_id,
                payload.client_id,
                payload.role,
                actor_principal_id=context.principal_id,
            )
        except PrincipalInvariantError as exc:
            subject_id = f"{normalized_id}:{payload.client_id.strip()}:{payload.role}"
            _audit_principal_rejection(store, "principal.client_role.removed", subject_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.global_role.added", normalized_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        except PrincipalInvariantError as exc:
            _audit_principal_rejection(store, "principal.global_role.removed", normalized_id, str(exc), context)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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

    @router.post("/principals/{principal_id}/identities")
    def add_identity(
        principal_id: str,
        payload: PrincipalIdentityRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        store = _store(request)
        principal = _find_principal(store, principal_id)
        if principal is None:
            raise HTTPException(status_code=404, detail="principal not found")
        config = _oidc_config(request)
        issuer = (payload.issuer or config.issuer).strip().rstrip("/")
        if issuer != config.issuer:
            raise HTTPException(status_code=422, detail="identity issuer must match configured Microsoft tenant")
        try:
            store.add_principal_identity(
                principal.principal_id,
                issuer,
                payload.subject,
                payload.subject_kind,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="identity is already linked") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.add_audit_event(
            "principal.identity.added",
            f"{principal.principal_id}:{payload.subject_kind}",
            "identity linked",
            approver_id=_actor_id(context),
        )
        return _principal_view_by_id(store, principal.principal_id)

    @router.delete("/principals/{principal_id}/identities")
    def remove_identity(
        principal_id: str,
        payload: PrincipalIdentityRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_management_access(context)
        store = _store(request)
        principal = _find_principal(store, principal_id)
        if principal is None:
            raise HTTPException(status_code=404, detail="principal not found")
        config = _oidc_config(request)
        issuer = (payload.issuer or config.issuer).strip().rstrip("/")
        if issuer != config.issuer:
            raise HTTPException(status_code=422, detail="identity issuer must match configured Microsoft tenant")
        try:
            store.remove_principal_identity(principal.principal_id, issuer, payload.subject, payload.subject_kind)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="identity link not found") from exc
        store.add_audit_event(
            "principal.identity.removed",
            f"{principal.principal_id}:{payload.subject_kind}",
            "identity unlinked",
            approver_id=_actor_id(context),
        )
        return _principal_view_by_id(store, principal.principal_id)

    return router


def _store(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if not isinstance(store, Store):
        raise HTTPException(status_code=503, detail="Local authorization store is unavailable.")
    return store


def _vault(request: Request) -> SecretVault:
    vault = getattr(request.app.state, "vault", None)
    if isinstance(vault, SecretVault):
        return vault
    return SecretVault(request.app.state.settings.vault_path)


def _oidc_config(request: Request) -> OidcConfig:
    return load_oidc_config(request.app.state.settings, _store(request), _vault(request))


def _oidc_config_view(config: OidcConfig) -> dict[str, object]:
    return {
        "enabled": config.enabled,
        "tenant_id": config.tenant_id,
        "client_id": config.client_id,
        "public_base_url": config.public_base_url,
        "auto_provision_enabled": config.auto_provision_enabled,
        "auto_provision_tenant_id": config.auto_provision_tenant_id,
        "auto_provision_client_id": config.auto_provision_client_id,
        "auto_provision_role": config.auto_provision_role,
        "client_secret_configured": config.client_secret_configured,
    }


def _create_browser_session(
    store: Store,
    settings: Settings,
    response: Response,
    principal_id: str,
    *,
    auth_method: Literal["local", "oidc"],
    user_agent: str,
) -> tuple[str, str]:
    session_token = generate_session_token()
    session_token_hash = hash_session_token(session_token)
    idle_expires_at, absolute_expires_at = session_expiries(
        idle_ttl_minutes=settings.session_idle_ttl_minutes,
        absolute_ttl_minutes=settings.session_absolute_ttl_minutes,
    )
    store.create_auth_session(
        session_token_hash,
        principal_id,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
        auth_method=auth_method,
        user_agent=user_agent,
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
    return session_token_hash, absolute_expires_at


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


def _audit_principal_rejection(
    store: Store,
    event_type: str,
    subject_id: str,
    detail: str,
    context: AuthContext,
) -> None:
    store.add_audit_event(event_type, subject_id, detail, approver_id=_actor_id(context))


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
        "identities": [
            {
                "issuer": identity.issuer,
                "subject": identity.subject,
                "subject_kind": identity.subject_kind,
                "created_at": identity.created_at,
                "last_login_at": identity.last_login_at,
            }
            for identity in store.list_principal_identities(principal.principal_id)
        ],
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
