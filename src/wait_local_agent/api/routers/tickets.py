"""Ticket and approval API routes."""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from wait_local_agent.api.context import ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import (
    ApprovalPayloadPatchRequest,
    ApprovalRequest,
    EndUserHaloSyncDraftRequest,
    EndUserMessageRequest,
)
from wait_local_agent.api.scopes import _approval_scope_visible, _operator_scope
from wait_local_agent.api.views import (
    _halopsa_client_mapping,
    _halopsa_draft_view,
    _operator_end_user_message_view,
    _redact_json_text,
    _redact_payload,
    _safe_external_ticket_id,
    _safe_json_object,
)
from wait_local_agent.client_scope import requested_client_from, resolve_client_scope
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_connectwise_approval_request,
    execute_halopsa_approval_request,
    execute_m365_approval_request,
    update_connectwise_approval_fields,
    update_halopsa_approval_fields,
)
from wait_local_agent.rbac import Role
from wait_local_agent.reports.renderers import redact_text
from wait_local_agent.store import QuarantinedTicketError, _normalize_client_id
from wait_local_agent.vault import SecretVault


def create_tickets_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    service = ctx.service
    operational_graph_service = ctx.operational_graph_service
    halopsa_client = ctx.halopsa_client
    connectwise_client = ctx.connectwise_client
    m365_client = ctx.m365_client
    smart_action_service = ctx.smart_action_service
    _approval_view = ctx.approval_view

    @router.get("/tickets")
    def tickets(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [asdict(ticket) for ticket in store.list_tickets(client_id=scope)]
    
    @router.get("/tickets/{ticket_id}/end-user-messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def ticket_end_user_messages(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
    ) -> list[dict[str, object]]:
        scope = _operator_scope(context, active_settings.client_id)
        ticket = store.get_ticket(ticket_id, client_id=scope, include_quarantine=False)
        ticket_client_id = _normalize_client_id(ticket.client_id) if ticket is not None else None
        if ticket_client_id is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return [
            _operator_end_user_message_view(message)
            for message in store.list_end_user_messages_for_operator(ticket_id, client_id=ticket_client_id)
        ]
    
    @router.post("/tickets/{ticket_id}/end-user-messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def add_ticket_end_user_message(
        ticket_id: str,
        payload: EndUserMessageRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        ticket = store.get_ticket(ticket_id, client_id=scope)
        ticket_client_id = _normalize_client_id(ticket.client_id) if ticket is not None else None
        if ticket_client_id is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        message = store.create_support_end_user_message(
            ticket_id,
            client_id=ticket_client_id,
            author_id=context.approver_id or "local-technician",
            body=payload.body,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _operator_end_user_message_view(message)
    
    @router.post("/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def draft_end_user_halopsa_sync(
        ticket_id: str,
        message_id: int,
        payload: EndUserHaloSyncDraftRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        external_ticket_id = payload.external_ticket_id.strip()
        if not _safe_external_ticket_id(external_ticket_id):
            raise HTTPException(status_code=422, detail="external HaloPSA ticket id is invalid")
        scope = _operator_scope(context, active_settings.client_id)
        local_ticket = store.get_ticket(ticket_id, client_id=scope)
        if local_ticket is None or not local_ticket.requester_id:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        scoped_client_id = _normalize_client_id(local_ticket.client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        message = next(
            (
                item
                for item in store.list_end_user_messages_for_operator(ticket_id, client_id=scoped_client_id)
                if item.id == message_id
            ),
            None,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="end-user message not found")
        expected_client_id = _halopsa_client_mapping(active_settings, scoped_client_id)
        if expected_client_id is None:
            raise HTTPException(status_code=409, detail="HaloPSA client mapping is not configured for this tenant")
        remote = halopsa_client.get_ticket(external_ticket_id)
        if remote.result.status != "ready" or len(remote.items) != 1:
            raise HTTPException(status_code=409, detail="HaloPSA ticket could not be verified")
        remote_ticket = remote.items[0]
        if getattr(remote_ticket, "client_id", "") != expected_client_id:
            raise HTTPException(status_code=403, detail="HaloPSA ticket is outside the configured tenant scope")
        expected_fields = {"note": message.body, "hiddenfromuser": False}
        for existing in store.list_approval_requests(client_id=scoped_client_id):
            if existing.subject_id != external_ticket_id or existing.action_type != "halopsa.add_note":
                continue
            if existing.status not in {"pending", "approved"}:
                continue
            existing_payload = _safe_json_object(existing.payload_json)
            if existing_payload.get("fields") != expected_fields:
                continue
            store.add_audit_event(
                "end_user.halopsa_sync_draft_reused",
                f"{ticket_id}:{message_id}",
                f"Existing HaloPSA sync approval {existing.id} reused for external ticket {external_ticket_id}",
                client_id=scoped_client_id,
            )
            return {
                "ticket_id": existing.subject_id,
                "action_type": "add_note",
                "payload_json": _redact_json_text(existing.payload_json),
                "payload": _redact_payload(existing_payload),
                "approval_required": True,
                "status": existing.status,
                "approval_request_id": existing.id,
            }
        draft = draft_halopsa_ticket_action(
            store,
            external_ticket_id,
            "add_note",
            expected_fields,
            client_id=scoped_client_id,
        )
        store.add_audit_event(
            "end_user.halopsa_sync_draft",
            f"{ticket_id}:{message_id}",
            f"HaloPSA sync draft created for external ticket {external_ticket_id}",
            client_id=scoped_client_id,
        )
        return _halopsa_draft_view(draft)
    
    @router.get("/tickets/{ticket_id}/summary")
    def summarize_ticket(ticket_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        if store.get_ticket(ticket_id, client_id=scope, include_quarantine=False) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        try:
            return asdict(service.summarize(ticket_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
    
    @router.get("/tickets/{ticket_id}/context")
    def ticket_context(ticket_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        if store.get_ticket(ticket_id, client_id=scope, include_quarantine=False) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        graph = operational_graph_service.ticket_context(scope, ticket_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        return asdict(graph)
    
    @router.get("/tickets/{ticket_id}/notes")
    def ticket_notes(ticket_id: str, context: ViewerAccess) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, None).client_id
        if scoped_client_id is None and context.role >= Role.ADMIN:
            ticket = store.get_ticket(ticket_id, include_quarantine=False)
            scoped_client_id = ticket.client_id if ticket is not None else None
        if scoped_client_id is None:
            return []
        notes = store.list_ticket_notes(ticket_id, client_id=scoped_client_id)
        return [
            {
                "id": note.id,
                "ticket_id": note.ticket_id,
                "author": redact_text(note.author),
                "body": redact_text(note.body),
                "created_at": note.created_at,
            }
            for note in notes
        ]
    
    @router.get("/tickets/{ticket_id}/status-history")
    def ticket_status_history(ticket_id: str, context: ViewerAccess) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, None).client_id
        if scoped_client_id is None and context.role >= Role.ADMIN:
            ticket = store.get_ticket(ticket_id, include_quarantine=False)
            scoped_client_id = ticket.client_id if ticket is not None else None
        if scoped_client_id is None:
            return []
        return store.list_ticket_status_history(ticket_id, client_id=scoped_client_id)
    
    @router.post("/tickets/{ticket_id}/approvals")
    def update_approval(
        ticket_id: str,
        request: ApprovalRequest,
        context: TechnicianAccess,
    ) -> dict[str, str]:
        scope = resolve_client_scope(context, None)
        if store.get_ticket(ticket_id, client_id=scope) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        store.set_approval(ticket_id, request.status, request.comment)
        return {"ticket_id": ticket_id, "status": request.status, "comment": request.comment}
    
    @router.get("/approval-requests")
    def approval_requests(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [_approval_view(request) for request in store.list_approval_requests(client_id=scope)]
    
    @router.get("/approval-requests/{request_id}")
    def approval_request_detail(request_id: int, context: ViewerAccess) -> dict[str, object]:
        request = store.get_approval_request(request_id)
        if request is None or not _approval_scope_visible(context, request):
            raise HTTPException(status_code=404, detail="approval request not found")
        return _approval_view(request)
    
    @router.patch("/approval-requests/{request_id}/payload")
    def update_approval_payload(
        request_id: int,
        request: ApprovalPayloadPatchRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_scope_visible(context, approval):
                raise KeyError(request_id)
            if approval.action_type.startswith("connectwise."):
                approval = update_connectwise_approval_fields(store, request_id, request.fields, request.comment)
            else:
                approval = update_halopsa_approval_fields(store, request_id, request.fields, request.comment)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except QuarantinedTicketError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)
    
    @router.post("/approval-requests/{request_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def update_approval_request(
        request_id: int,
        payload: ApprovalRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            existing_approval = store.get_approval_request(request_id)
            if existing_approval is None:
                raise KeyError(request_id)
            # A decision is an authorization operation: a known foreign
            # approval must fail with 403, while detail/payload lookups keep
            # hiding foreign existence with 404.
            resolve_client_scope(context, existing_approval.client_id)
            if not _approval_scope_visible(context, existing_approval):
                raise KeyError(request_id)
            if (
                existing_approval.action_type.startswith("m365.")
                or existing_approval.action_type == "teams.message.send"
            ) and context.role < Role.ADMIN:
                raise PermissionError("M365 approvals require admin authority")
            if existing_approval.action_type.startswith("smart_action:"):
                smart_action_service.update_approval(
                    request_id,
                    payload.status,
                    payload.comment,
                    approver=context.approver_id or "api",
                    approver_role=context.role,
                )
                approval = store.get_approval_request(request_id) or existing_approval
            else:
                approval = store.update_approval_request(
                    request_id,
                    payload.status,
                    payload.comment,
                    approver_id=context.approver_id,
                    allow_completed=store.get_workflow_run_for_approval(request_id) is not None,
                )
            if payload.status == "approved" and approval.action_type.startswith("halopsa."):
                try:
                    approval = execute_halopsa_approval_request(store, halopsa_client, request_id)
                except RuntimeError:
                    approval = store.get_approval_request(request_id) or approval
            if payload.status == "approved" and approval.action_type.startswith("connectwise."):
                try:
                    approval = execute_connectwise_approval_request(store, connectwise_client, request_id)
                except RuntimeError:
                    approval = store.get_approval_request(request_id) or approval
            if payload.status == "approved" and approval.action_type.startswith("m365."):
                try:
                    approval = execute_m365_approval_request(
                        store,
                        m365_client,
                        SecretVault(active_settings.vault_path),
                        request_id,
                    )
                except RuntimeError:
                    approval = store.get_approval_request(request_id) or approval
            return _approval_view(approval)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuarantinedTicketError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:  # pragma: no cover
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
