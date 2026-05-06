from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from wait_local_agent.config import Settings, load_settings
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_halopsa_approval_request,
    list_connector_statuses,
    list_secret_records,
)
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.knowledge import KnowledgeIngestionService
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store
from wait_local_agent.workflows import list_workflow_templates, run_workflow_template


class ApprovalRequest(BaseModel):
    status: Literal["approved", "rejected", "pending"]
    comment: str = ""


class KnowledgeIngestRequest(BaseModel):
    path: str


class HaloDraftRequest(BaseModel):
    action_type: Literal[
        "add_note",
        "update_status",
        "assign_technician",
        "draft_response",
        "update_ticket_fields",
    ]
    fields: dict[str, object]


class WorkflowRunRequest(BaseModel):
    ticket_id: str


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or load_settings()
    store = Store(active_settings.data_path)
    service = TicketIntelligenceService(
        store=store,
        settings=active_settings,
        provider=provider_from_settings(active_settings),
    )
    halopsa_client = HaloPSAClient(active_settings)

    app = FastAPI(title="WAIT Local Agent", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "write_actions_enabled": active_settings.allow_write_actions,
            "http_probing_enabled": active_settings.allow_http_probing,
            "cloud_fallback_enabled": active_settings.allow_cloud_fallback,
            "halopsa_configured": bool(
                active_settings.halopsa_base_url
                and active_settings.halopsa_client_id
                and active_settings.halopsa_client_secret
                and active_settings.halopsa_tenant
            ),
        }

    @app.get("/settings/providers")
    def providers() -> dict[str, object]:
        return {
            "local_model_provider": active_settings.local_model_provider,
            "local_model_base_url": active_settings.local_model_base_url,
            "local_model_name": active_settings.local_model_name,
            "local_model_timeout_seconds": active_settings.local_model_timeout_seconds,
            "llm_inference_enabled": active_settings.allow_llm_inference,
            "vector_backend": active_settings.vector_backend,
        }

    @app.get("/tickets")
    def tickets() -> list[dict[str, object]]:
        return [asdict(ticket) for ticket in store.list_tickets()]

    @app.get("/tickets/{ticket_id}/summary")
    def summarize_ticket(ticket_id: str) -> dict[str, object]:
        try:
            return asdict(service.summarize(ticket_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc

    @app.post("/tickets/{ticket_id}/approvals")
    def update_approval(ticket_id: str, request: ApprovalRequest) -> dict[str, str]:
        if store.get_ticket(ticket_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        store.set_approval(ticket_id, request.status, request.comment)
        return {"ticket_id": ticket_id, "status": request.status, "comment": request.comment}

    @app.get("/approval-requests")
    def approval_requests() -> list[dict[str, object]]:
        return [asdict(request) for request in store.list_approval_requests()]

    @app.post("/approval-requests/{request_id}")
    def update_approval_request(request_id: int, request: ApprovalRequest) -> dict[str, object]:
        try:
            approval = store.update_approval_request(request_id, request.status, request.comment)
            if request.status == "approved" and approval.action_type.startswith("halopsa."):
                try:
                    approval = execute_halopsa_approval_request(store, halopsa_client, request_id)
                except RuntimeError:
                    approval = store.get_approval_request(request_id) or approval
            return asdict(approval)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc

    @app.get("/audit")
    def audit() -> list[dict[str, object]]:
        return [asdict(event) for event in store.list_audit_events()]

    @app.get("/event-history")
    def event_history() -> list[dict[str, object]]:
        return [asdict(event) for event in store.list_event_history()]

    @app.get("/connectors")
    def connectors() -> list[dict[str, object]]:
        return [asdict(status) for status in list_connector_statuses(active_settings)]

    @app.get("/secrets")
    def secrets() -> list[dict[str, object]]:
        return [asdict(secret) for secret in list_secret_records(active_settings)]

    @app.post("/connectors/halopsa/tickets/{ticket_id}/drafts")
    def create_halopsa_draft(ticket_id: str, request: HaloDraftRequest) -> dict[str, object]:
        try:
            draft = draft_halopsa_ticket_action(
                store,
                ticket_id,
                request.action_type,
                request.fields,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(draft)

    @app.get("/connectors/halopsa/health")
    def halopsa_health() -> dict[str, object]:
        result = halopsa_client.health()
        _audit_halopsa_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/halopsa/write-health")
    def halopsa_write_health() -> dict[str, object]:
        result = halopsa_client.write_health()
        store.add_audit_event("halopsa.write_health", "halopsa", result.status)
        return asdict(result)

    @app.post("/connectors/halopsa/approval-requests/{request_id}/execute")
    def execute_halopsa_approval(request_id: int) -> dict[str, object]:
        try:
            return asdict(execute_halopsa_approval_request(store, halopsa_client, request_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/connectors/halopsa/tickets")
    def halopsa_tickets(page: int = 1, page_size: int = 50) -> dict[str, object]:
        response = halopsa_client.list_tickets(page=page, page_size=page_size)
        return _halopsa_response("tickets.list", response)

    @app.get("/connectors/halopsa/tickets/{ticket_id}")
    def halopsa_ticket(ticket_id: str) -> dict[str, object]:
        response = halopsa_client.get_ticket(ticket_id)
        return _halopsa_response("tickets.get", response)

    @app.get("/connectors/halopsa/tickets/{ticket_id}/notes")
    def halopsa_ticket_notes(ticket_id: str) -> dict[str, object]:
        response = halopsa_client.list_ticket_notes(ticket_id)
        return _halopsa_response("tickets.notes", response)

    @app.get("/connectors/halopsa/clients")
    def halopsa_clients(page: int = 1, page_size: int = 50) -> dict[str, object]:
        response = halopsa_client.list_clients(page=page, page_size=page_size)
        return _halopsa_response("clients.list", response)

    @app.get("/connectors/halopsa/clients/{client_id}/assets")
    def halopsa_client_assets(client_id: str) -> dict[str, object]:
        response = halopsa_client.list_client_assets(client_id)
        return _halopsa_response("clients.assets", response)

    @app.get("/connectors/halopsa/categories")
    def halopsa_categories() -> dict[str, object]:
        response = halopsa_client.list_categories()
        return _halopsa_response("categories.list", response)

    @app.get("/workflows/templates")
    def workflow_templates() -> list[dict[str, object]]:
        return [asdict(template) for template in list_workflow_templates()]

    @app.post("/workflows/templates/{template_id}/runs")
    def run_workflow(template_id: str, request: WorkflowRunRequest) -> dict[str, object]:
        try:
            return asdict(run_workflow_template(store, template_id, request.ticket_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workflow template not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc

    @app.get("/workflow-runs")
    def workflow_runs() -> list[dict[str, object]]:
        return [asdict(run) for run in store.list_workflow_runs()]

    @app.post("/knowledge/ingest")
    def ingest_knowledge(request: KnowledgeIngestRequest) -> list[dict[str, object]]:
        try:
            service = KnowledgeIngestionService(store, active_settings.allowed_doc_root)
            documents = service.ingest_path(Path(request.path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(document) for document in documents]

    @app.get("/knowledge/documents")
    def knowledge_documents() -> list[dict[str, object]]:
        return [asdict(document) for document in store.list_knowledge_documents()]

    @app.get("/knowledge/search")
    def knowledge_search(q: str, limit: int = 3) -> list[dict[str, object]]:
        return [asdict(chunk) for chunk in store.search_knowledge_chunks(q, limit=limit)]

    def _halopsa_response(read_type: str, response: HaloReadResponse) -> dict[str, object]:
        _audit_halopsa_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
        }

    def _audit_halopsa_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("halopsa.read", read_type, f"{status} count={count}")

    return app
