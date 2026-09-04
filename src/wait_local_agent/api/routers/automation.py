"""Automation, smart-action, tools, and MCP API routes."""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from wait_local_agent.api.context import ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import EventIngestRequest, SmartActionInvokeRequest
from wait_local_agent.api.scopes import _request_correlation_id, _resolve_detail_scope, _singular_action_client
from wait_local_agent.api.views import (
    _event_delivery_view,
    _event_dispatch_view,
    _smart_action_run_view,
)
from wait_local_agent.client_scope import requested_client_from, resolve_client_scope
from wait_local_agent.event_dispatch import EventDispatchError
from wait_local_agent.mcp import (
    MAX_MCP_REQUEST_BYTES,
    MCP_PROTOCOL_VERSION,
    McpProtocolError,
    origin_allowed,
    protocol_error_response,
)
from wait_local_agent.rbac import Role, resolve_auth_context
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.store import _normalize_client_id


def create_automation_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    agent_service = ctx.agent_service
    smart_action_service = ctx.smart_action_service
    mcp_server = ctx.mcp_server
    event_dispatcher = ctx.event_dispatcher

    @router.get("/smart-actions")
    def smart_actions(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(manifest) for manifest in smart_action_service.list()]

    @router.get("/tools")
    def tools(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(tool) for tool in agent_service.list_tools()]

    @router.get("/mcp")
    def mcp_get() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})

    @router.post("/mcp")
    @limiter.limit(active_settings.rate_limit_connector)
    async def mcp_endpoint(request: Request) -> Response:
        origin = request.headers.get("origin")
        request_origin = str(request.base_url).rstrip("/")
        if not origin_allowed(origin, request_origin, active_settings.mcp_allowed_origins):
            return JSONResponse(status_code=403, content={"detail": "invalid MCP origin"})
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_MCP_REQUEST_BYTES:
                    return JSONResponse(status_code=413, content={"detail": "MCP request is too large"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "invalid content length"})
        try:
            body = await request.body()
            if len(body) > MAX_MCP_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": "MCP request is too large"})
            message = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(status_code=400, content={"detail": "MCP request must be JSON"})
        request_id = message.get("id") if isinstance(message, dict) else None
        try:
            context = resolve_auth_context(
                active_settings,
                request.headers.get("authorization"),
                store,
            )
            protocol_header = request.headers.get("mcp-protocol-version")
            if protocol_header and protocol_header not in {MCP_PROTOCOL_VERSION, "2025-03-26"}:
                raise McpProtocolError(-32600, "unsupported MCP protocol version")
            response, new_session_id = mcp_server.handle(
                message,
                context=context,
                session_id=request.headers.get("mcp-session-id"),
            )
        except McpProtocolError as exc:
            response = protocol_error_response(request_id, exc)
            new_session_id = None
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": redact_text(str(exc.detail))},
                headers=dict(exc.headers or {}),
            )
        headers = {"MCP-Session-Id": new_session_id} if new_session_id else None
        if response is None:
            return Response(status_code=202, headers=headers)
        return JSONResponse(content=response, headers=headers)

    @router.post("/automation/events")
    @limiter.limit(active_settings.rate_limit_general)
    def ingest_automation_event(
        request: Request,
        payload: EventIngestRequest,
        context: TechnicianAccess,
        idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        idempotency_key = idempotency_key_header or payload.idempotency_key
        if idempotency_key is None:
            raise HTTPException(status_code=422, detail="Idempotency-Key header or idempotency_key is required")
        try:
            result = event_dispatcher.dispatch(
                event_type=payload.event_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                payload=payload.payload,
                idempotency_key=idempotency_key,
                client_id=scoped_client_id,
                actor=context.approver_id or "webhook",
                max_retries=payload.max_retries,
                retry_delay_seconds=payload.retry_delay_seconds,
            )
        except EventDispatchError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="event entity not found") from exc
        return _event_dispatch_view(result)

    @router.get("/automation/event-deliveries")
    def event_deliveries(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [_event_delivery_view(delivery) for delivery in store.list_event_deliveries(scope)]

    @router.get("/automation/event-deliveries/{delivery_id}")
    def event_delivery_detail(delivery_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        delivery = store.get_event_delivery(delivery_id, scope)
        if delivery is None:
            raise HTTPException(status_code=404, detail="event delivery not found")
        return _event_delivery_view(delivery)

    @router.post("/automation/event-deliveries/{delivery_id}/retry")
    @limiter.limit(active_settings.rate_limit_general)
    def retry_event_delivery(
        request: Request,
        delivery_id: int,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        requested_client_id = None
        if not context.demo_mode and context.role < Role.ADMIN:
            requested_client_id = _normalize_client_id(context.client_id)
        scope = _resolve_detail_scope(context, requested_client_id)
        delivery = store.get_event_delivery(delivery_id, scope)
        if delivery is None:
            raise HTTPException(status_code=404, detail="event delivery not found")
        try:
            result = event_dispatcher.retry(
                delivery_id,
                client_id=delivery.client_id,
                actor=context.approver_id or "operator",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="event delivery not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _event_dispatch_view(result)

    @router.get("/smart-actions/runs")
    def smart_action_runs(context: ViewerAccess, client_id: str | None = None) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [
            _smart_action_run_view(run)
            for run in smart_action_service.store.list_smart_action_runs(client_id=scope)
        ]

    @router.get("/smart-actions/runs/{run_id}")
    def smart_action_run_detail(run_id: int, context: ViewerAccess, client_id: str | None = None) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = smart_action_service.store.get_smart_action_run(run_id, client_id=scope)
        if run is None:
            raise HTTPException(status_code=404, detail="smart action run not found")
        return _smart_action_run_view(run)

    @router.get("/smart-actions/{action_id}")
    def smart_action_detail(action_id: str, _: ViewerAccess) -> dict[str, object]:
        try:
            return asdict(smart_action_service.describe(action_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="smart action not found") from exc

    @router.post("/smart-actions/{action_id}/invoke")
    def invoke_smart_action(
        action_id: str,
        payload: SmartActionInvokeRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            manifest = smart_action_service.describe(action_id)
            if manifest.required_role.strip().lower() == "admin" and context.role < Role.ADMIN:
                raise HTTPException(status_code=403, detail="smart action requires admin authority")
            scoped_client_id = _singular_action_client(
                store,
                context,
                payload.client_id,
                payload.payload,
            )
            result = smart_action_service.invoke(
                action_id,
                payload.payload,
                context.approver_id or "api",
                confirm=payload.confirm,
                client_id=scoped_client_id,
                correlation_id=_request_correlation_id(request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="smart action not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(result)


    return router


__all__ = ["create_automation_router"]
