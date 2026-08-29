from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from wait_local_agent.capabilities import (
    MICROSOFT_ADMIN_CAPABILITY,
    SUPPORTED_CAPABILITIES,
    grant_capability,
    list_capability_grants,
    list_principals,
    revoke_capability,
)
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.store import Store

ViewerAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER))]
AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]


class CapabilityGrantRequest(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    capability_key: str = Field(default=MICROSOFT_ADMIN_CAPABILITY, min_length=1, max_length=64)
    client_id: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")


def create_access_router() -> APIRouter:
    router = APIRouter(prefix="/access", tags=["Microsoft administrator access"])

    @router.get("/effective")
    def effective_access(context: ViewerAccess) -> dict[str, object]:
        grants = [
            {"capability_key": capability_key, "client_id": client_id}
            for capability_key, client_id in sorted(
                context.capability_grants,
                key=lambda item: (item[0], item[1] or ""),
            )
        ]
        return {
            "principal_id": context.principal_id,
            "supported_capabilities": sorted(SUPPORTED_CAPABILITIES),
            "grants": grants,
        }

    @router.get("/principals")
    def principals(request: Request, context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        return [asdict(principal) for principal in list_principals(_store(request))]

    @router.get("/grants")
    def grants(
        request: Request,
        context: AdminAccess,
        principal_id: str | None = Query(default=None, max_length=128),
        capability_key: str | None = Query(default=None, max_length=64),
    ) -> list[dict[str, object]]:
        _require_msp_operator(context)
        try:
            rows = list_capability_grants(
                _store(request),
                principal_id=principal_id,
                capability_key=capability_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [asdict(grant) for grant in rows]

    @router.post("/grants")
    def create_grant(
        payload: CapabilityGrantRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            grant = grant_capability(
                _store(request),
                principal_id=payload.principal_id,
                capability_key=payload.capability_key,
                client_id=payload.client_id,
                actor_id=_actor_id(context),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="principal or client was not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _audit(request, "capability.granted", _grant_entity(grant.principal_id, grant.capability_key, grant.client_id))
        return asdict(grant)

    @router.post("/grants/revoke")
    def revoke_grant(
        payload: CapabilityGrantRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        _require_live_management(context)
        try:
            grant = revoke_capability(
                _store(request),
                principal_id=payload.principal_id,
                capability_key=payload.capability_key,
                client_id=payload.client_id,
                actor_id=_actor_id(context),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="capability grant was not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _audit(request, "capability.revoked", _grant_entity(grant.principal_id, grant.capability_key, grant.client_id))
        return asdict(grant)

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
        raise HTTPException(status_code=403, detail="capability grants cannot be changed in demo mode")


def _actor_id(context: AuthContext) -> str:
    return context.principal_id or context.approver_id or "bootstrap-admin"


def _grant_entity(principal_id: str, capability_key: str, client_id: str | None) -> str:
    return f"{principal_id}:{capability_key}:{client_id or '*'}"


def _audit(request: Request, event_type: str, entity_id: str) -> None:
    _store(request).add_audit_event(event_type, entity_id, "succeeded")
