"""Technician chat and end-user API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from wait_local_agent.api.context import ApiContext, EndUserAccess, TechnicianAccess
from wait_local_agent.api.schemas import (
    EndUserBrandingResponse,
    EndUserMessageRequest,
    EndUserTicketCreateRequest,
    TechnicianChatMessageRequest,
    TechnicianChatRequest,
    TechnicianChatSessionCreateRequest,
)
from wait_local_agent.api.scopes import (
    _end_user_client_id,
    _end_user_read_client_id,
    _request_correlation_id,
    _resolve_detail_scope,
    _singular_action_client,
)
from wait_local_agent.api.views import (
    _end_user_brand_color,
    _end_user_brand_logo_data_uri,
    _end_user_branding_text,
    _end_user_message_view,
    _end_user_ticket_view,
    _invoke_technician_chat_message,
    _safe_end_user_ticket_id,
    _technician_chat_session_view,
)
from wait_local_agent.client_scope import resolve_client_scope
from wait_local_agent.rbac import Role
from wait_local_agent.store import QuarantinedTicketError
from wait_local_agent.technician_chat import TechnicianChatParseError


def create_end_user_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    smart_action_service = ctx.smart_action_service
    agent_service = ctx.agent_service

    @router.post("/technician/chat")
    @limiter.limit(active_settings.rate_limit_connector)
    def technician_chat(
        payload: TechnicianChatRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _singular_action_client(
            store,
            context,
            payload.client_id,
            {"ticket_id": payload.ticket_id} if payload.ticket_id is not None else {},
        )
        try:
            return _invoke_technician_chat_message(
                store,
                smart_action_service,
                agent_service,
                payload.message,
                ticket_id=payload.ticket_id,
                actor=context.approver_id or "api",
                client_id=scoped_client_id,
                correlation_id=_request_correlation_id(request),
            )
        except TechnicianChatParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="requested technician action is unavailable") from exc
    
    @router.post("/technician/chat/sessions")
    @limiter.limit(active_settings.rate_limit_connector)
    def create_technician_chat_session(
        payload: TechnicianChatSessionCreateRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, payload.client_id)
        scoped_client_id = scope.client_id
        if payload.ticket_id:
            ticket = store.get_ticket(payload.ticket_id, scope)
            if ticket is None:
                raise HTTPException(status_code=404, detail="ticket not found in client scope")
            scoped_client_id = ticket.client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="chat sessions require a client scope")
        try:
            session = store.create_technician_chat_session(
                client_id=scoped_client_id,
                principal_id=context.approver_id or "api",
                ticket_id=payload.ticket_id,
            )
        except QuarantinedTicketError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _technician_chat_session_view(store, session)
    
    @router.get("/technician/chat/sessions")
    @limiter.limit(active_settings.rate_limit_connector)
    def list_technician_chat_sessions(
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        sessions = store.list_technician_chat_sessions(
            client_id=scope,
            principal_id=principal_id,
        )
        return [_technician_chat_session_view(store, session) for session in sessions]
    
    @router.get("/technician/chat/sessions/{session_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def get_technician_chat_session(
        session_id: str,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        session = store.get_technician_chat_session(
            session_id,
            client_id=scope,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="technician chat session not found")
        return _technician_chat_session_view(store, session)
    
    @router.post("/technician/chat/sessions/{session_id}/messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def send_technician_chat_message(
        session_id: str,
        payload: TechnicianChatMessageRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        session = store.get_technician_chat_session(
            session_id,
            client_id=scope,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="technician chat session not found")
        try:
            return _invoke_technician_chat_message(
                store,
                smart_action_service,
                agent_service,
                payload.message,
                ticket_id=payload.ticket_id or session.ticket_id,
                actor=context.approver_id or "api",
                client_id=session.client_id,
                session_id=session.id,
                principal_id=principal_id,
                correlation_id=_request_correlation_id(request),
            )
        except TechnicianChatParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="requested technician action is unavailable") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found in client scope") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    
    @router.post("/technician/chat/sessions/{session_id}/close")
    @limiter.limit(active_settings.rate_limit_connector)
    def close_technician_chat_session(
        session_id: str,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        session = store.close_technician_chat_session(
            session_id,
            client_id=scope,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="technician chat session not found")
        return _technician_chat_session_view(store, session)
    
    @router.get("/end-user/config", response_model=EndUserBrandingResponse)
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_config(
        request: Request,
        context: EndUserAccess,
    ) -> EndUserBrandingResponse:
        _end_user_client_id(context)
        return EndUserBrandingResponse(
            brand_name=_end_user_branding_text(active_settings.end_user_brand_name, "WAIT Support"),
            brand_tagline=_end_user_branding_text(active_settings.end_user_brand_tagline, "Private help desk"),
            brand_logo_data_uri=_end_user_brand_logo_data_uri(active_settings.end_user_brand_logo_data_uri),
            brand_accent_color=_end_user_brand_color(active_settings.end_user_brand_accent_color, "#1f6f55"),
            brand_surface_color=_end_user_brand_color(active_settings.end_user_brand_surface_color, "#f3f5f2"),
        )
    
    @router.post("/end-user/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_create_ticket(
        payload: EndUserTicketCreateRequest,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        client_id = _end_user_client_id(context)
        ticket = store.create_end_user_ticket(
            client_id=client_id,
            requester_id=context.principal_id or "",
            subject=payload.subject,
            body=payload.body,
        )
        return _end_user_ticket_view(ticket)
    
    @router.get("/end-user/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_ticket_status(
        ticket_id: str,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        client_id = _end_user_read_client_id(context)
        if not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        ticket = store.get_end_user_ticket(
            ticket_id,
            client_id=client_id,
            requester_id=context.principal_id or "",
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _end_user_ticket_view(ticket)
    
    @router.get("/end-user/tickets/{ticket_id}/messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_ticket_messages(
        ticket_id: str,
        request: Request,
        context: EndUserAccess,
    ) -> list[dict[str, object]]:
        client_id = _end_user_read_client_id(context)
        if not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        ticket = store.get_end_user_ticket(
            ticket_id,
            client_id=client_id,
            requester_id=context.principal_id or "",
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return [
            _end_user_message_view(message)
            for message in store.list_end_user_messages(
                ticket_id,
                client_id=client_id,
                requester_id=context.principal_id or "",
            )
        ]
    
    @router.post("/end-user/tickets/{ticket_id}/messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_add_ticket_message(
        ticket_id: str,
        payload: EndUserMessageRequest,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        client_id = _end_user_client_id(context)
        if not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        message = store.create_end_user_message(
            ticket_id,
            client_id=client_id,
            requester_id=context.principal_id or "",
            body=payload.body,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _end_user_message_view(message)
    
    @router.post("/end-user/tickets/{ticket_id}/escalate")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_escalate_ticket(
        ticket_id: str,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        client_id = _end_user_client_id(context)
        if not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        ticket = store.escalate_end_user_ticket(
            ticket_id,
            client_id=client_id,
            requester_id=context.principal_id or "",
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _end_user_ticket_view(ticket)

    return router
