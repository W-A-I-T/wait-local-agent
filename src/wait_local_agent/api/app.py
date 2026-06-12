from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel

from wait_local_agent.config import Settings, load_settings
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_halopsa_approval_request,
    list_connector_statuses,
    list_secret_records,
    update_halopsa_approval_fields,
)
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.hudu import HuduClient, HuduReadResponse
from wait_local_agent.knowledge import ingestion_service_from_settings
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.security import auth_required, require_bearer_authorization
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store
from wait_local_agent.vector_search import search_backend_from_settings
from wait_local_agent.workflows import list_workflow_templates, run_workflow_template


class ApprovalRequest(BaseModel):
    status: Literal["approved", "rejected", "pending"]
    comment: str = ""


class KnowledgeIngestRequest(BaseModel):
    path: str
    parser: str | None = None
    ocr: bool | None = None


class ApprovalPayloadPatchRequest(BaseModel):
    fields: dict[str, object]
    comment: str = "Draft edited before approval"


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
    hudu_client = HuduClient(active_settings)

    def require_api_auth(authorization: Annotated[str | None, Header()] = None) -> None:
        require_bearer_authorization(active_settings, authorization)

    app = FastAPI(
        title="WAIT Local Agent",
        version="0.1.0",
        dependencies=[Depends(require_api_auth)],
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "write_actions_enabled": active_settings.allow_write_actions,
            "http_probing_enabled": active_settings.allow_http_probing,
            "cloud_fallback_enabled": active_settings.allow_cloud_fallback,
            "llm_inference_enabled": active_settings.allow_llm_inference,
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
            "secrets_backend": active_settings.secrets_backend,
            "halopsa_configured": bool(
                active_settings.halopsa_base_url
                and active_settings.halopsa_client_id
                and active_settings.halopsa_client_secret
                and active_settings.halopsa_tenant
            ),
            "hudu_configured": bool(
                active_settings.hudu_base_url and active_settings.hudu_api_key
            ),
        }

    @app.get("/settings/security")
    def security_settings() -> dict[str, object]:
        return {
            "api_token_configured": bool(active_settings.api_token),
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
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
            "document_parser": active_settings.document_parser,
            "ocr_enabled": active_settings.allow_ocr,
            "embedding_provider": active_settings.embedding_provider,
            "embedding_model": active_settings.embedding_model,
            "qdrant_collection": active_settings.qdrant_collection,
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
        return [_approval_view(request) for request in store.list_approval_requests()]

    @app.get("/approval-requests/{request_id}")
    def approval_request_detail(request_id: int) -> dict[str, object]:
        request = store.get_approval_request(request_id)
        if request is None:
            raise HTTPException(status_code=404, detail="approval request not found")
        return _approval_view(request)

    @app.patch("/approval-requests/{request_id}/payload")
    def update_approval_payload(
        request_id: int, request: ApprovalPayloadPatchRequest
    ) -> dict[str, object]:
        try:
            approval = update_halopsa_approval_fields(
                store,
                request_id,
                request.fields,
                request.comment,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/approval-requests/{request_id}")
    def update_approval_request(request_id: int, request: ApprovalRequest) -> dict[str, object]:
        try:
            approval = store.update_approval_request(request_id, request.status, request.comment)
            if request.status == "approved" and approval.action_type.startswith("halopsa."):
                try:
                    approval = execute_halopsa_approval_request(store, halopsa_client, request_id)
                except RuntimeError:
                    approval = store.get_approval_request(request_id) or approval
            return _approval_view(approval)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc

    @app.get("/audit")
    def audit() -> list[dict[str, object]]:
        return [asdict(event) for event in store.list_audit_events()]

    @app.get("/audit/export")
    def audit_export(export_format: Literal["json", "csv"] = "json") -> Response:
        events = [asdict(event) for event in store.list_audit_events()]
        if export_format == "csv":
            output = io.StringIO()
            fieldnames = ["id", "event_type", "subject_id", "detail", "created_at"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(events)
            return Response(
                output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="wait-audit-events.csv"'},
            )
        return Response(
            json.dumps(events, sort_keys=True, indent=2) + "\n",
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="wait-audit-events.json"'},
        )

    @app.get("/audit-events/export")
    def audit_events_export(
        format: Literal["json", "csv"] = "json",
        from_: Annotated[datetime | None, Query(alias="from")] = None,
        to_: Annotated[datetime | None, Query(alias="to")] = None,
    ) -> Response:
        all_events = store.list_audit_events()
        filtered = [
            e for e in all_events
            if (from_ is None or datetime.fromisoformat(e.created_at) >= from_.astimezone(UTC))
            and (to_ is None or datetime.fromisoformat(e.created_at) <= to_.astimezone(UTC))
        ]
        events = [asdict(e) for e in filtered]
        if format == "csv":
            output = io.StringIO()
            fieldnames = ["id", "event_type", "subject_id", "detail", "created_at"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(events)
            return Response(
                output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="wait-audit-events.csv"'},
            )
        return Response(
            json.dumps({"count": len(events), "events": events}),
            media_type="application/json",
        )

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

    @app.get("/connectors/hudu/health")
    def hudu_health() -> dict[str, object]:
        result = hudu_client.health()
        _audit_hudu_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/hudu/companies")
    def hudu_companies(page: int = 1, page_size: int | None = None) -> dict[str, object]:
        response = hudu_client.list_companies(page=page, page_size=page_size)
        return _hudu_response("companies.list", response)

    @app.get("/connectors/hudu/articles")
    def hudu_articles(
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = hudu_client.list_articles(
            company_id=company_id,
            page=page,
            page_size=page_size,
        )
        return _hudu_response("articles.list", response)

    @app.get("/connectors/hudu/articles/{article_id}")
    def hudu_article(article_id: str) -> dict[str, object]:
        response = hudu_client.get_article(article_id)
        return _hudu_response("articles.get", response)

    @app.get("/connectors/hudu/folders")
    def hudu_folders(
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = hudu_client.list_folders(
            company_id=company_id,
            page=page,
            page_size=page_size,
        )
        return _hudu_response("folders.list", response)

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

    @app.get("/workflow-runs/{run_id}")
    def workflow_run_detail(run_id: int) -> dict[str, object]:
        run = store.get_workflow_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        template = next(
            (item for item in list_workflow_templates() if item.id == run.template_id),
            None,
        )
        approval = (
            store.get_approval_request(run.approval_request_id)
            if run.approval_request_id is not None
            else None
        )
        return {
            **asdict(run),
            "template": asdict(template) if template is not None else None,
            "approval_request": _approval_view(approval) if approval is not None else None,
            "events": [
                asdict(event) for event in store.list_event_history_for_subject(run.ticket_id)
            ],
        }

    @app.post("/knowledge/ingest")
    def ingest_knowledge(request: KnowledgeIngestRequest) -> list[dict[str, object]]:
        try:
            settings = replace(
                active_settings,
                document_parser=request.parser or active_settings.document_parser,
                allow_ocr=active_settings.allow_ocr if request.ocr is None else request.ocr,
            )
            service = ingestion_service_from_settings(store, settings)
            documents = service.ingest_path(Path(request.path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(document) for document in documents]

    @app.get("/knowledge/documents")
    def knowledge_documents() -> list[dict[str, object]]:
        return [asdict(document) for document in store.list_knowledge_documents()]

    @app.get("/knowledge/search")
    def knowledge_search(
        q: str,
        limit: int = 3,
        backend: str | None = None,
    ) -> list[dict[str, object]]:
        try:
            settings = replace(
                active_settings,
                vector_backend=backend or active_settings.vector_backend,
            )
            search_backend = search_backend_from_settings(settings, store)
            return [asdict(chunk) for chunk in search_backend.search(q, limit=limit)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _halopsa_response(read_type: str, response: HaloReadResponse) -> dict[str, object]:
        _audit_halopsa_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
        }

    def _hudu_response(read_type: str, response: HuduReadResponse) -> dict[str, object]:
        _audit_hudu_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
        }

    def _audit_halopsa_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("halopsa.read", read_type, f"{status} count={count}")

    def _audit_hudu_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("hudu.read", read_type, f"{status} count={count}")

    def _approval_view(request) -> dict[str, object]:
        payload = _safe_json_object(request.payload_json)
        workflow_run = (
            store.get_workflow_run_for_approval(request.id)
            if request.id is not None
            else None
        )
        can_execute, block_reason = _approval_execution_state(request)
        return {
            **asdict(request),
            "payload": _redact_payload(payload),
            "can_execute": can_execute,
            "block_reason": block_reason,
            "workflow_run_id": workflow_run.id if workflow_run is not None else None,
        }

    def _approval_execution_state(request) -> tuple[bool, str]:
        if not request.action_type.startswith("halopsa."):
            return False, "Only HaloPSA approvals have live execution in this release."
        if request.status != "approved":
            return False, "Approval must be approved before execution."
        if request.execution_status == "succeeded":
            return False, "Approval request has already executed successfully."
        if not hasattr(halopsa_client, "write_health"):
            return False, "HaloPSA write health is unavailable."
        write_health = halopsa_client.write_health()
        if write_health.status != "ready":
            return False, write_health.message
        return True, ""

    return app


def _safe_json_object(payload_json: str) -> dict[str, object]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "api_key",
    "password",
    "apikey",
    "auth_token",
    "bearer",
    "authorization",
    "x-api-key",
    "client_secret",
    "access_token",
)


def _redact_payload(payload: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if any(secret in key.lower() for secret in SENSITIVE_KEY_PARTS):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = _redact_value(value)
    return redacted


def _redact_value(value: object) -> object:
    if isinstance(value, dict):
        return _redact_payload(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value
