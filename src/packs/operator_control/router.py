"""API surfaces for operator identity lifecycle and unified activity."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from wait_local_agent.client_scope import resolve_client_scope
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.store import Store

from .activity import activity_to_dict, list_activity
from .identity import (
    IdentityConflictError,
    create_principal,
    deactivate_principal,
    get_principal_detail,
    list_principal_details,
    principal_to_dict,
    remove_client_role,
    revoke_credentials,
    rotate_credential,
    set_client_role,
    set_msp_admin,
    update_principal,
)

AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]
ViewerAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER))]


class ClientRoleBinding(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    role: Literal["end_user", "viewer", "technician", "admin"]

    model_config = ConfigDict(extra="forbid")


class PrincipalCreateRequest(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    kind: Literal["customer", "staff"] = "staff"
    display_name: str = Field(default="", max_length=200)
    client_roles: list[ClientRoleBinding] = Field(default_factory=list, max_length=50)
    msp_admin: bool = False
    issue_credential: bool = True

    model_config = ConfigDict(extra="forbid")


class PrincipalPatchRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    active: bool | None = None

    model_config = ConfigDict(extra="forbid")


class RoleRequest(BaseModel):
    role: Literal["end_user", "viewer", "technician", "admin"]

    model_config = ConfigDict(extra="forbid")


class MspAdminRequest(BaseModel):
    enabled: bool

    model_config = ConfigDict(extra="forbid")


def create_router() -> APIRouter:
    router = APIRouter(tags=["Operator control"])

    @router.get("/status")
    def status(context: ViewerAccess) -> dict[str, object]:
        return {
            "status": "ready",
            "principal_management": bool(context.is_msp_admin or context.demo_mode),
            "credential_rotation": not context.demo_mode and context.is_msp_admin,
            "unified_activity": True,
        }

    @router.get("/principals")
    def principals(request: Request, context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        return [principal_to_dict(row) for row in list_principal_details(_store(request))]

    @router.get("/principals/{principal_id}")
    def principal(principal_id: str, request: Request, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        try:
            return principal_to_dict(get_principal_detail(_store(request), principal_id))
        except (KeyError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.post("/principals")
    def create_identity(
        payload: PrincipalCreateRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            principal_row, token = create_principal(
                _store(request),
                principal_id=payload.principal_id,
                kind=payload.kind,
                display_name=payload.display_name,
                client_roles=tuple((row.client_id, row.role) for row in payload.client_roles),
                msp_admin=payload.msp_admin,
                issue_credential=payload.issue_credential,
            )
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(request, "principal.created", principal_row.principal_id, context)
        return {
            "principal": principal_to_dict(principal_row),
            "credential": token,
            "credential_notice": (
                "This credential is returned once. Store it securely; WAIT persists only its hash."
                if token is not None
                else "No credential was issued."
            ),
        }

    @router.patch("/principals/{principal_id}")
    def patch_identity(
        principal_id: str,
        payload: PrincipalPatchRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        if payload.display_name is None and payload.active is None:
            raise HTTPException(status_code=422, detail="display_name or active is required")
        try:
            row = update_principal(
                _store(request),
                principal_id=principal_id,
                display_name=payload.display_name,
                active=payload.active,
                actor_principal_id=context.principal_id,
            )
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(request, "principal.updated", row.principal_id, context)
        return principal_to_dict(row)

    @router.delete("/principals/{principal_id}")
    def delete_identity(principal_id: str, request: Request, context: AdminAccess) -> dict[str, object]:
        """Soft-delete a principal to preserve audit and historical attribution."""

        _require_msp_operator(context)
        _require_live_management(context)
        try:
            row = deactivate_principal(
                _store(request),
                principal_id=principal_id,
                actor_principal_id=context.principal_id,
            )
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(request, "principal.deactivated", row.principal_id, context)
        return principal_to_dict(row)

    @router.post("/principals/{principal_id}/credentials/rotate")
    def rotate_identity_credential(
        principal_id: str,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            row, token = rotate_credential(_store(request), principal_id=principal_id)
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(request, "principal.credential.rotated", row.principal_id, context)
        return {
            "principal": principal_to_dict(row),
            "credential": token,
            "credential_notice": (
                "This credential is returned once. "
                "All prior credentials for this principal are revoked."
            ),
        }

    @router.post("/principals/{principal_id}/credentials/revoke-all")
    def revoke_identity_credentials(
        principal_id: str,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            row = revoke_credentials(
                _store(request),
                principal_id=principal_id,
                actor_principal_id=context.principal_id,
            )
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(request, "principal.credentials.revoked", row.principal_id, context)
        return principal_to_dict(row)

    @router.put("/principals/{principal_id}/client-roles/{client_id}")
    def put_client_role(
        principal_id: str,
        client_id: str,
        payload: RoleRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            row = set_client_role(
                _store(request),
                principal_id=principal_id,
                client_id=client_id,
                role=payload.role,
            )
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(request, "principal.client_role.updated", f"{row.principal_id}:{client_id}", context)
        return principal_to_dict(row)

    @router.delete("/principals/{principal_id}/client-roles/{client_id}")
    def delete_client_role(
        principal_id: str,
        client_id: str,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            row = remove_client_role(
                _store(request),
                principal_id=principal_id,
                client_id=client_id,
                actor_principal_id=context.principal_id,
            )
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(request, "principal.client_role.removed", f"{row.principal_id}:{client_id}", context)
        return principal_to_dict(row)

    @router.put("/principals/{principal_id}/msp-admin")
    def put_msp_admin(
        principal_id: str,
        payload: MspAdminRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            row = set_msp_admin(
                _store(request),
                principal_id=principal_id,
                enabled=payload.enabled,
                actor_principal_id=context.principal_id,
            )
        except (KeyError, ValueError, IdentityConflictError) as exc:
            raise _http_error(exc) from exc
        _audit(
            request,
            "principal.msp_admin.granted" if payload.enabled else "principal.msp_admin.revoked",
            row.principal_id,
            context,
        )
        return principal_to_dict(row)

    @router.get("/activity/runs")
    def activity_runs(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = Query(default=None, max_length=128),
        kinds: str | None = Query(default=None, max_length=256),
        status_filter: str | None = Query(default=None, alias="status", max_length=64),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id, allow_all=True)
        kind_set = (
            frozenset(part.strip() for part in kinds.split(",") if part.strip())
            if kinds is not None
            else None
        )
        try:
            rows = list_activity(
                _store(request),
                scope=scope,
                kinds=kind_set,
                status=status_filter,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [activity_to_dict(row) for row in rows]

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
        raise HTTPException(status_code=403, detail="identity management is read-only in demo mode")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="principal, client, or role binding was not found")
    if isinstance(exc, IdentityConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _audit(request: Request, event_type: str, subject_id: str, context: AuthContext) -> None:
    actor = context.principal_id or context.approver_id or "bootstrap-admin"
    _store(request).add_audit_event(event_type, subject_id, f"actor={actor}")
