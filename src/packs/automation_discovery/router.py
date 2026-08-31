"""FastAPI surface for historical PSA automation discovery."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from wait_local_agent.client_scope import BoundClients, resolve_client_scope
from wait_local_agent.rbac import AuthContext, Role, require_role

from .service import (
    HistoricalTimeEntry,
    build_historical_discovery,
    build_mapping_readiness,
    category_catalog,
    ensure_schema,
    import_time_entries,
)

ViewerAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER))]
AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]


class HistoricalTimeEntryInput(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=256)
    connector_instance_id: str = Field(min_length=1, max_length=128)
    external_time_entry_id: str = Field(min_length=1, max_length=256)
    minutes: int = Field(ge=0, le=1440)
    work_type: str = Field(default="", max_length=160)
    occurred_at: datetime
    source_system: str = Field(min_length=1, max_length=80)

    model_config = ConfigDict(extra="forbid")


class HistoricalTimeEntryImportRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    entries: list[HistoricalTimeEntryInput] = Field(min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")


def create_router() -> APIRouter:
    router = APIRouter(tags=["Automation discovery"])

    @router.get("/status")
    def status(request: Request) -> dict[str, object]:
        ensure_schema(request.app.state.store)
        return {
            "status": "ready",
            "external_writes": False,
            "discovery_source": "tenant-scoped local PSA ticket evidence",
            "measured_labor_source": "normalized PSA time entries when available",
        }

    @router.get("/categories")
    def categories(_: ViewerAccess) -> list[dict[str, object]]:
        return category_catalog()

    @router.get("/historical")
    def historical(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = Query(default=None, max_length=128),
        days: int = Query(default=60, ge=7, le=365),
        min_tickets: int = Query(default=3, ge=2, le=100),
    ) -> dict[str, object]:
        target_client = _client_id(context, client_id)
        result = build_historical_discovery(
            request.app.state.store,
            client_id=target_client,
            days=days,
            min_tickets=min_tickets,
        )
        request.app.state.store.add_audit_event(
            "automation_discovery.historical_report",
            target_client,
            f"days={days} min_tickets={min_tickets} opportunity_count={result['opportunity_count']}",
        )
        return result

    @router.get("/mapping-readiness")
    def mapping_readiness(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = Query(default=None, max_length=128),
    ) -> dict[str, object]:
        target_client = _client_id(context, client_id)
        result = build_mapping_readiness(request.app.state.store, client_id=target_client)
        request.app.state.store.add_audit_event(
            "automation_discovery.mapping_readiness",
            target_client,
            f"verified={result['verified_count']} unverified={result['unverified_count']}",
        )
        return result

    @router.post("/time-entries/import")
    def time_entry_import(
        payload: HistoricalTimeEntryImportRequest,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        target_client = _client_id(context, payload.client_id)
        store = request.app.state.store
        valid_ticket_ids = {ticket.id for ticket in store.list_tickets(client_id=target_client)}
        mappings = store.list_client_connector_mappings(BoundClients(frozenset({target_client})))
        permitted_connector_ids = {
            mapping.connector_instance_id
            for mapping in mappings
            if mapping.verified == 1 and mapping.client_id == target_client
        }
        permitted_connector_ids.update(
            instance.connector_instance_id
            for instance in store.list_connector_instances()
            if instance.client_id == target_client
        )
        normalized: list[HistoricalTimeEntry] = []
        for item in payload.entries:
            if item.ticket_id not in valid_ticket_ids:
                raise HTTPException(status_code=400, detail=f"ticket is not in the selected client scope: {item.ticket_id}")
            if item.connector_instance_id not in permitted_connector_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"connector is not verified or client-bound for the selected client: {item.connector_instance_id}",
                )
            normalized.append(
                HistoricalTimeEntry(
                    client_id=target_client,
                    ticket_id=item.ticket_id,
                    connector_instance_id=item.connector_instance_id,
                    external_time_entry_id=item.external_time_entry_id,
                    minutes=item.minutes,
                    work_type=item.work_type,
                    occurred_at=item.occurred_at.isoformat(),
                    source_system=item.source_system,
                )
            )
        result = import_time_entries(store, normalized)
        store.add_audit_event(
            "automation_discovery.time_entries_imported",
            target_client,
            f"inserted={result['inserted']} duplicate={result['duplicate']} rejected={result['rejected']}",
        )
        return {
            "client_id": target_client,
            **result,
            "external_writes": False,
        }

    return router


def _client_id(context: AuthContext, requested_client_id: str | None) -> str:
    scope = resolve_client_scope(context, requested_client_id)
    if scope.client_id is None:
        raise HTTPException(status_code=400, detail="automation discovery requires one explicit client")
    return scope.client_id
