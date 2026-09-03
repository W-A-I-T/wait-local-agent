"""API surfaces for operator identity lifecycle and unified activity."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from wait_local_agent.client_scope import requested_client_from, resolve_client_scope
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.store import Store

from .activity import activity_to_dict, list_activity

ViewerAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER))]


def create_router() -> APIRouter:
    router = APIRouter(tags=["Operator control"])

    @router.get("/status")
    def status(context: ViewerAccess) -> dict[str, object]:
        return {
            "status": "ready",
            "unified_activity": True,
        }

    @router.get("/activity/runs")
    def activity_runs(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = Query(default=None, max_length=128),
        kinds: str | None = Query(default=None, max_length=256),
        status_filter: str | None = Query(default=None, alias="status", max_length=64),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
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
