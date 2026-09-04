"""Psa Connectors API routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, HTTPException, Request

from wait_local_agent.api.context import AdminAccess, ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import ConnectWiseDraftRequest, HaloDraftRequest
from wait_local_agent.api.scopes import (
    _approval_scope_visible,
    _require_msp_operator,
    _resolve_detail_scope,
)
from wait_local_agent.api.views import _connectwise_draft_view, _halopsa_draft_view, redact_value
from wait_local_agent.autotask import AutotaskClient, AutotaskReadResponse
from wait_local_agent.client_scope import BoundClients, requested_client_from, resolve_client_scope
from wait_local_agent.connector_factory import ConnectorFactoryError
from wait_local_agent.connectors import (
    draft_connectwise_ticket_action,
    draft_halopsa_ticket_action,
    execute_connectwise_approval_request,
    execute_halopsa_approval_request,
    list_connector_statuses,
)
from wait_local_agent.connectwise import ConnectWiseClient, ConnectWiseReadResponse
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.ingestion_poller import IngestionPoller
from wait_local_agent.servicenow import ServiceNowClient, ServiceNowReadResponse
from wait_local_agent.store import QuarantinedTicketError
from wait_local_agent.syncro import SyncroClient, SyncroCommentsResponse, SyncroReadResponse


def create_psa_connectors_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    halopsa_client = ctx.halopsa_client
    connectwise_client = ctx.connectwise_client
    syncro_client = ctx.syncro_client
    servicenow_client = ctx.servicenow_client
    autotask_client = ctx.autotask_client
    _connector_read_client = ctx.connector_read_client
    _approval_view = ctx.approval_view

    def _halopsa_response(
        read_type: str,
        response: HaloReadResponse,
    ) -> dict[str, object]:
        items = response.items
        result = asdict(response.result)
        result["count"] = len(items)
        _audit_halopsa_read(read_type, response.result.status, len(items))
        return {
            "result": result,
            "items": [asdict(item) for item in items],
        }
    def _connectwise_response(read_type: str, response: ConnectWiseReadResponse) -> dict[str, object]:
        _audit_connectwise_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": response.items,
        }
    def _syncro_response(read_type: str, response: SyncroReadResponse) -> dict[str, object]:
        _audit_syncro_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": response.items,
        }
    def _syncro_comments_response(read_type: str, response: SyncroCommentsResponse) -> dict[str, object]:
        _audit_syncro_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(item)) for item in response.items],
            "meta": cast(dict[str, object], redact_value(response.meta)),
        }
    def _servicenow_response(
        read_type: str,
        response: ServiceNowReadResponse,
    ) -> dict[str, object]:
        _audit_servicenow_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": response.items,
        }
    def _audit_halopsa_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("halopsa.read", read_type, f"{status} count={count}")
    def _audit_connectwise_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("connectwise.read", read_type, f"{status} count={count}")
    def _audit_syncro_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("syncro.read", read_type, f"{status} count={count}")
    def _audit_servicenow_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("servicenow.read", read_type, f"{status} count={count}")
    def _autotask_response(
        read_type: str,
        response: AutotaskReadResponse,
    ) -> dict[str, object]:
        _audit_autotask_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": response.items,
        }
    def _audit_autotask_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("autotask.read", read_type, f"{status} count={count}")

    @router.post("/connectors/instances/{connector_instance_id}/sync")
    def connector_instance_sync_now(
        connector_instance_id: str,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        instance = store.get_connector_instance(connector_instance_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="connector instance not found")
        if not active_settings.allow_http_probing:
            raise HTTPException(status_code=409, detail="connector read probing is disabled")
        if str(instance.status).strip().lower() != "active":
            raise HTTPException(status_code=409, detail="connector instance is not active")
        poller = IngestionPoller(store, base_settings=active_settings)
        try:
            summary = poller.poll_instance(
                connector_instance_id,
                max_pages=25,
                page_size=50,
                deadline_seconds=60.0,
                lease_ttl_seconds=300.0,
            )
        except (ConnectorFactoryError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="connector sync could not run") from exc
        store.add_audit_event(
            "connector.sync_triggered", connector_instance_id, f"manual sync -> {summary.status}"
        )
        return asdict(summary)

    @router.get("/connectors")
    def connectors(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(status) for status in list_connector_statuses(active_settings)]

    @router.post("/connectors/halopsa/tickets/{ticket_id}/drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def create_halopsa_draft(
        ticket_id: str,
        payload: HaloDraftRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None and not context.demo_mode:
            raise HTTPException(status_code=403, detail="draft actions require a client scope")
        try:
            draft = draft_halopsa_ticket_action(
                store,
                ticket_id,
                payload.action_type,
                payload.fields,
                client_id=scoped_client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _halopsa_draft_view(draft)

    @router.post("/connectors/connectwise/tickets/{ticket_id}/drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def create_connectwise_draft(
        ticket_id: str,
        payload: ConnectWiseDraftRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            draft = draft_connectwise_ticket_action(
                store,
                ticket_id,
                payload.action_type,
                payload.fields,
                client_id=resolve_client_scope(context, payload.client_id).client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _connectwise_draft_view(draft)

    @router.get("/connectors/halopsa/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = halopsa_client.health()
        _audit_halopsa_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/halopsa/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = halopsa_client.write_health()
        store.add_audit_event("halopsa.write_health", "halopsa", result.status)
        return asdict(result)

    @router.post("/connectors/halopsa/approval-requests/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_halopsa_approval(
        request_id: int,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_scope_visible(context, approval):
                raise KeyError(request_id)
            return _approval_view(execute_halopsa_approval_request(store, halopsa_client, request_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except QuarantinedTicketError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/connectors/halopsa/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_tickets(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int = 50,
        client_id: str | None = None,
    ) -> dict[str, object]:
        # Halo tickets cannot be filtered to a WAIT client without guessing
        # from provider customer names.  Keep the appliance-wide result for
        # operators, but fail closed for bound principals.
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        if isinstance(scope, BoundClients):
            raise HTTPException(status_code=409, detail={"code": "client_scope_unsupported"})
        response = halopsa_client.list_tickets(page=page, page_size=page_size)
        return _halopsa_response("tickets.list", response)

    @router.get("/connectors/halopsa/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_ticket(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HaloPSAClient,
            _connector_read_client(request, context, "halopsa", halopsa_client, requested_client_id=client_id),
        )
        response = client.get_ticket(ticket_id)
        return _halopsa_response("tickets.get", response)

    @router.get("/connectors/halopsa/tickets/{ticket_id}/notes")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_ticket_notes(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HaloPSAClient,
            _connector_read_client(request, context, "halopsa", halopsa_client, requested_client_id=client_id),
        )
        response = client.list_ticket_notes(ticket_id)
        return _halopsa_response("tickets.notes", response)

    @router.get("/connectors/halopsa/clients")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_clients(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int = 50,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HaloPSAClient,
            _connector_read_client(request, context, "halopsa", halopsa_client, requested_client_id=client_id),
        )
        response = client.list_clients(page=page, page_size=page_size)
        return _halopsa_response("clients.list", response)

    @router.get("/connectors/halopsa/clients/{client_id}/assets")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_client_assets(client_id: str, request: Request, context: ViewerAccess) -> dict[str, object]:
        # The path client id is validated against the principal's scope here; it must not be
        # re-submitted as a *requested* client, or an appliance-wide (AllClients) caller would be
        # narrowed to a bound scope and fail closed for lack of a client-scoped instance.
        scoped_client_id = _resolve_detail_scope(context, client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="client scope is required")
        client = cast(
            HaloPSAClient,
            _connector_read_client(request, context, "halopsa", halopsa_client),
        )
        response = client.list_client_assets(scoped_client_id)
        return _halopsa_response("clients.assets", response)

    @router.get("/connectors/halopsa/categories")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_categories(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HaloPSAClient,
            _connector_read_client(request, context, "halopsa", halopsa_client, requested_client_id=client_id),
        )
        response = client.list_categories()
        return _halopsa_response("categories.list", response)

    @router.get("/connectors/connectwise/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = connectwise_client.health()
        _audit_connectwise_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/connectwise/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = connectwise_client.write_health()
        store.add_audit_event("connectwise.write_health", "connectwise", result.status)
        return asdict(result)

    @router.post("/connectors/connectwise/approval-requests/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_connectwise_approval(
        request_id: int,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_scope_visible(context, approval):
                raise KeyError(request_id)
            return _approval_view(execute_connectwise_approval_request(store, connectwise_client, request_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except QuarantinedTicketError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/connectors/connectwise/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_tickets(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        conditions: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ConnectWiseClient,
            _connector_read_client(request, context, "connectwise", connectwise_client, requested_client_id=client_id),
        )
        response = client.list_tickets(
            page=page,
            page_size=(page_size if page_size is not None else active_settings.connectwise_page_size),
            conditions=conditions,
        )
        return _connectwise_response("tickets.list", response)

    @router.get("/connectors/connectwise/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_ticket(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ConnectWiseClient,
            _connector_read_client(request, context, "connectwise", connectwise_client, requested_client_id=client_id),
        )
        response = client.get_ticket(ticket_id)
        return _connectwise_response("tickets.get", response)

    @router.get("/connectors/connectwise/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_companies(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        conditions: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ConnectWiseClient,
            _connector_read_client(request, context, "connectwise", connectwise_client, requested_client_id=client_id),
        )
        response = client.list_companies(
            page=page,
            page_size=(page_size if page_size is not None else active_settings.connectwise_page_size),
            conditions=conditions,
        )
        return _connectwise_response("companies.list", response)

    @router.get("/connectors/syncro/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = syncro_client.health()
        _audit_syncro_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/syncro/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_tickets(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        query: str | None = None,
        customer_id: str | None = None,
        status: str | None = None,
        since_updated_at: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SyncroClient,
            _connector_read_client(request, context, "syncro", syncro_client, requested_client_id=client_id),
        )
        response = client.list_tickets(
            page=page,
            query=query,
            customer_id=customer_id,
            status=status,
            since_updated_at=since_updated_at,
        )
        return _syncro_response("tickets.list", response)

    @router.get("/connectors/syncro/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_ticket(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SyncroClient,
            _connector_read_client(request, context, "syncro", syncro_client, requested_client_id=client_id),
        )
        response = client.get_ticket(ticket_id)
        return _syncro_response("tickets.get", response)

    @router.get("/connectors/syncro/tickets/{ticket_id}/comments")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_ticket_comments(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        per_page: int = 10,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SyncroClient,
            _connector_read_client(request, context, "syncro", syncro_client, requested_client_id=client_id),
        )
        response = client.list_ticket_comments(
            ticket_id,
            page=page,
            per_page=per_page,
        )
        return _syncro_comments_response("tickets.comments", response)

    @router.get("/connectors/syncro/customers")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_customers(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        query: str | None = None,
        business_name: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SyncroClient,
            _connector_read_client(request, context, "syncro", syncro_client, requested_client_id=client_id),
        )
        response = client.list_customers(
            page=page,
            query=query,
            business_name=business_name,
        )
        return _syncro_response("customers.list", response)

    @router.get("/connectors/syncro/customers/{customer_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_customer(
        customer_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SyncroClient,
            _connector_read_client(request, context, "syncro", syncro_client, requested_client_id=client_id),
        )
        response = client.get_customer(customer_id)
        return _syncro_response("customers.get", response)

    @router.get("/connectors/servicenow/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = servicenow_client.health()
        _audit_servicenow_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/servicenow/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = servicenow_client.write_health()
        store.add_audit_event("servicenow.write_health", "servicenow", result.status)
        return asdict(result)

    @router.get("/connectors/servicenow/incidents")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_incidents(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        query: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ServiceNowClient,
            _connector_read_client(request, context, "servicenow", servicenow_client, requested_client_id=client_id),
        )
        response = client.list_incidents(
            page=page,
            page_size=(page_size if page_size is not None else active_settings.servicenow_page_size),
            query=query,
        )
        return _servicenow_response("incidents.list", response)

    @router.get("/connectors/servicenow/incidents/{sys_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_incident(
        sys_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ServiceNowClient,
            _connector_read_client(request, context, "servicenow", servicenow_client, requested_client_id=client_id),
        )
        response = client.get_incident(sys_id)
        return _servicenow_response("incidents.get", response)

    @router.get("/connectors/servicenow/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_companies(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        query: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ServiceNowClient,
            _connector_read_client(request, context, "servicenow", servicenow_client, requested_client_id=client_id),
        )
        response = client.list_companies(
            page=page,
            page_size=(page_size if page_size is not None else active_settings.servicenow_page_size),
            query=query,
        )
        return _servicenow_response("companies.list", response)

    @router.get("/connectors/servicenow/companies/{sys_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_company(
        sys_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ServiceNowClient,
            _connector_read_client(request, context, "servicenow", servicenow_client, requested_client_id=client_id),
        )
        response = client.get_company(sys_id)
        return _servicenow_response("companies.get", response)

    @router.get("/connectors/autotask/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = autotask_client.health()
        _audit_autotask_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/autotask/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = autotask_client.write_health()
        store.add_audit_event("autotask.write_health", "autotask", result.status)
        return asdict(result)

    @router.get("/connectors/autotask/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_tickets(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            AutotaskClient,
            _connector_read_client(request, context, "autotask", autotask_client, requested_client_id=client_id),
        )
        response = client.list_tickets(
            page=page,
            page_size=(page_size if page_size is not None else active_settings.autotask_page_size),
        )
        return _autotask_response("tickets.list", response)

    @router.get("/connectors/autotask/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_ticket(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            AutotaskClient,
            _connector_read_client(request, context, "autotask", autotask_client, requested_client_id=client_id),
        )
        response = client.get_ticket(ticket_id)
        return _autotask_response("tickets.get", response)

    @router.get("/connectors/autotask/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_companies(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            AutotaskClient,
            _connector_read_client(request, context, "autotask", autotask_client, requested_client_id=client_id),
        )
        response = client.list_companies(
            page=page,
            page_size=(page_size if page_size is not None else active_settings.autotask_page_size),
        )
        return _autotask_response("companies.list", response)

    @router.get("/connectors/autotask/companies/{company_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_company(
        company_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            AutotaskClient,
            _connector_read_client(request, context, "autotask", autotask_client, requested_client_id=client_id),
        )
        response = client.get_company(company_id)
        return _autotask_response("companies.get", response)

    return router


__all__ = ["create_psa_connectors_router"]
