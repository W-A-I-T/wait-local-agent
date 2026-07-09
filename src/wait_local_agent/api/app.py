from __future__ import annotations

import csv
import io
import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

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
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.scheduler import SchedulerManager
from wait_local_agent.security import auth_required
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store
from wait_local_agent.update_channel import UpdateStatusCache, check_for_updates
from wait_local_agent.vector_search import search_backend_from_settings
from wait_local_agent.workflows import (
    get_workflow_template,
    list_workflow_templates,
    run_workflow_template,
)

ViewerAccess = Annotated[AuthContext, Depends(require_role(Role.VIEWER))]
TechnicianAccess = Annotated[AuthContext, Depends(require_role(Role.TECHNICIAN))]
AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]


class ApprovalRequest(BaseModel):
    status: Literal["approved", "rejected", "pending"]
    comment: str = ""


class KnowledgeIngestRequest(BaseModel):
    path: str
    parser: str | None = None
    ocr: bool | None = None
    client_id: str | None = None


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
    client_id: str | None = None


class WorkflowRunRequest(BaseModel):
    ticket_id: str
    client_id: str | None = None


class ScheduledJobCreateRequest(BaseModel):
    template_id: str
    cron: str
    params: dict[str, object]


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or load_settings()
    store = Store(active_settings.data_path)
    scheduler = SchedulerManager(store, enabled=active_settings.scheduler_enabled)
    service = TicketIntelligenceService(
        store=store,
        settings=active_settings,
        provider=provider_from_settings(active_settings),
    )
    halopsa_client = HaloPSAClient(active_settings)
    hudu_client = HuduClient(active_settings)
    update_status_cache = UpdateStatusCache(ttl_seconds=3600.0)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown()

    app = FastAPI(
        title="WAIT Local Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[active_settings.rate_limit_general],
        headers_enabled=False,
        retry_after="delta-seconds",
        enabled=active_settings.rate_limit_enabled,
    )
    app.state.settings = active_settings
    app.state.store = store
    app.state.scheduler = scheduler
    app.state.limiter = limiter
    app.state.update_status_cache = update_status_cache
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/health")
    @limiter.exempt
    def health(request: Request, _: ViewerAccess) -> dict[str, object]:
        return {
            "status": "ok",
            "write_actions_enabled": active_settings.allow_write_actions,
            "http_probing_enabled": active_settings.allow_http_probing,
            "cloud_fallback_enabled": active_settings.allow_cloud_fallback,
            "llm_inference_enabled": active_settings.allow_llm_inference,
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
            "secrets_backend": active_settings.secrets_backend,
            "scheduler_enabled": active_settings.scheduler_enabled,
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

    @app.get("/auth/role")
    def auth_role(context: ViewerAccess) -> dict[str, object]:
        return {
            "role": context.role.label(),
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
        }

    @app.get("/settings/security")
    def security_settings(_: AdminAccess) -> dict[str, object]:
        return {
            "api_token_configured": bool(active_settings.api_token),
            "admin_token_configured": bool(active_settings.admin_token),
            "tech_token_configured": bool(active_settings.tech_token),
            "viewer_token_configured": bool(active_settings.viewer_token),
            "api_auth_required": auth_required(active_settings),
            "demo_mode": active_settings.demo_mode,
        }

    @app.get("/settings/providers")
    def providers(_: ViewerAccess) -> dict[str, object]:
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

    @app.get("/update-status")
    def update_status(_: AdminAccess) -> dict[str, object]:
        return update_status_cache.get_status(lambda: check_for_updates(active_settings)).to_dict()

    @app.get("/tickets")
    def tickets(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [asdict(ticket) for ticket in store.list_tickets(client_id=client_id)]

    @app.get("/tickets/{ticket_id}/summary")
    def summarize_ticket(ticket_id: str, _: ViewerAccess) -> dict[str, object]:
        try:
            return asdict(service.summarize(ticket_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc

    @app.post("/tickets/{ticket_id}/approvals")
    def update_approval(
        ticket_id: str,
        request: ApprovalRequest,
        _: TechnicianAccess,
    ) -> dict[str, str]:
        if store.get_ticket(ticket_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        store.set_approval(ticket_id, request.status, request.comment)
        return {"ticket_id": ticket_id, "status": request.status, "comment": request.comment}

    @app.get("/approval-requests")
    def approval_requests(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            _approval_view(request) for request in store.list_approval_requests(client_id=client_id)
        ]

    @app.get("/approval-requests/{request_id}")
    def approval_request_detail(request_id: int, _: ViewerAccess) -> dict[str, object]:
        request = store.get_approval_request(request_id)
        if request is None:
            raise HTTPException(status_code=404, detail="approval request not found")
        return _approval_view(request)

    @app.patch("/approval-requests/{request_id}/payload")
    def update_approval_payload(
        request_id: int,
        request: ApprovalPayloadPatchRequest,
        _: TechnicianAccess,
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
    @limiter.limit(active_settings.rate_limit_connector)
    def update_approval_request(
        request_id: int,
        payload: ApprovalRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            approval = store.update_approval_request(
                request_id,
                payload.status,
                payload.comment,
                approver_id=context.approver_id,
            )
            if payload.status == "approved" and approval.action_type.startswith("halopsa."):
                try:
                    approval = execute_halopsa_approval_request(store, halopsa_client, request_id)
                except RuntimeError:
                    approval = store.get_approval_request(request_id) or approval
            return _approval_view(approval)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc

    @app.get("/audit")
    def audit(_: ViewerAccess, client_id: str | None = None) -> list[dict[str, object]]:
        return [asdict(event) for event in store.list_audit_events(client_id=client_id)]

    @app.get("/audit/export")
    def audit_export(
        _: AdminAccess,
        export_format: Literal["json", "csv"] = "json",
        client_id: str | None = None,
    ) -> Response:
        events = [asdict(event) for event in store.list_audit_events(client_id=client_id)]
        if export_format == "csv":
            output = io.StringIO()
            fieldnames = ["id", "event_type", "subject_id", "detail", "created_at", "client_id", "approver_id"]
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
        _: AdminAccess,
        format: Literal["json", "csv"] = "json",
        from_: Annotated[datetime | None, Query(alias="from")] = None,
        to_: Annotated[datetime | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> Response:
        all_events = store.list_audit_events(client_id=client_id)
        filtered = [
            e for e in all_events
            if (from_ is None or datetime.fromisoformat(e.created_at) >= from_.astimezone(UTC))
            and (to_ is None or datetime.fromisoformat(e.created_at) <= to_.astimezone(UTC))
        ]
        events = [asdict(e) for e in filtered]
        if format == "csv":
            output = io.StringIO()
            fieldnames = ["id", "event_type", "subject_id", "detail", "created_at", "client_id", "approver_id"]
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
    def event_history(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(event) for event in store.list_event_history()]

    @app.get("/connectors")
    def connectors(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(status) for status in list_connector_statuses(active_settings)]

    @app.get("/secrets")
    def secrets(_: AdminAccess) -> list[dict[str, object]]:
        return [asdict(secret) for secret in list_secret_records(active_settings)]

    @app.post("/connectors/halopsa/tickets/{ticket_id}/drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def create_halopsa_draft(
        ticket_id: str,
        payload: HaloDraftRequest,
        request: Request,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            draft = draft_halopsa_ticket_action(
                store,
                ticket_id,
                payload.action_type,
                payload.fields,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(draft)

    @app.get("/connectors/halopsa/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = halopsa_client.health()
        _audit_halopsa_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/halopsa/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = halopsa_client.write_health()
        store.add_audit_event("halopsa.write_health", "halopsa", result.status)
        return asdict(result)

    @app.post("/connectors/halopsa/approval-requests/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_halopsa_approval(
        request_id: int,
        request: Request,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            return asdict(execute_halopsa_approval_request(store, halopsa_client, request_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/connectors/halopsa/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_tickets(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        response = halopsa_client.list_tickets(page=page, page_size=page_size)
        return _halopsa_response("tickets.list", response)

    @app.get("/connectors/halopsa/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_ticket(ticket_id: str, request: Request, _: ViewerAccess) -> dict[str, object]:
        response = halopsa_client.get_ticket(ticket_id)
        return _halopsa_response("tickets.get", response)

    @app.get("/connectors/halopsa/tickets/{ticket_id}/notes")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_ticket_notes(ticket_id: str, request: Request, _: ViewerAccess) -> dict[str, object]:
        response = halopsa_client.list_ticket_notes(ticket_id)
        return _halopsa_response("tickets.notes", response)

    @app.get("/connectors/halopsa/clients")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_clients(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        response = halopsa_client.list_clients(page=page, page_size=page_size)
        return _halopsa_response("clients.list", response)

    @app.get("/connectors/halopsa/clients/{client_id}/assets")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_client_assets(client_id: str, request: Request, _: ViewerAccess) -> dict[str, object]:
        response = halopsa_client.list_client_assets(client_id)
        return _halopsa_response("clients.assets", response)

    @app.get("/connectors/halopsa/categories")
    @limiter.limit(active_settings.rate_limit_connector)
    def halopsa_categories(request: Request, _: ViewerAccess) -> dict[str, object]:
        response = halopsa_client.list_categories()
        return _halopsa_response("categories.list", response)

    @app.get("/connectors/hudu/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = hudu_client.health()
        _audit_hudu_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/hudu/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_companies(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = hudu_client.list_companies(page=page, page_size=page_size)
        return _hudu_response("companies.list", response)

    @app.get("/connectors/hudu/articles")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_articles(
        request: Request,
        _: ViewerAccess,
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
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_article(article_id: str, request: Request, _: ViewerAccess) -> dict[str, object]:
        response = hudu_client.get_article(article_id)
        return _hudu_response("articles.get", response)

    @app.get("/connectors/hudu/folders")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_folders(
        request: Request,
        _: ViewerAccess,
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
    def workflow_templates(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(template) for template in list_workflow_templates()]

    @app.get("/scheduled-jobs")
    def scheduled_jobs(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [_scheduled_job_view(job) for job in scheduler.list_jobs(client_id=client_id)]

    @app.post("/scheduled-jobs")
    def create_scheduled_job(
        request: ScheduledJobCreateRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        if get_workflow_template(request.template_id) is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        ticket_id = _scheduled_ticket_id(request.params)
        if store.get_ticket(ticket_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        try:
            scheduled_job = scheduler.register(
                request.template_id,
                request.cron,
                request.params,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    @app.post("/scheduled-jobs/{job_id}/pause")
    def pause_scheduled_job(job_id: int, _: TechnicianAccess) -> dict[str, object]:
        try:
            return _scheduled_job_view(scheduler.pause(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @app.post("/scheduled-jobs/{job_id}/resume")
    def resume_scheduled_job(job_id: int, _: TechnicianAccess) -> dict[str, object]:
        try:
            return _scheduled_job_view(scheduler.resume(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @app.delete("/scheduled-jobs/{job_id}")
    def delete_scheduled_job(job_id: int, _: TechnicianAccess) -> dict[str, object]:
        try:
            return _scheduled_job_view(scheduler.remove(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @app.post("/workflows/templates/{template_id}/runs")
    def run_workflow(
        template_id: str,
        request: WorkflowRunRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            return asdict(
                run_workflow_template(
                    store,
                    template_id,
                    request.ticket_id,
                    client_id=request.client_id,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workflow template not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc

    @app.get("/workflow-runs")
    def workflow_runs(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [asdict(run) for run in store.list_workflow_runs(client_id=client_id)]

    @app.get("/workflow-runs/{run_id}")
    def workflow_run_detail(run_id: int, _: ViewerAccess) -> dict[str, object]:
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
    def ingest_knowledge(
        request: KnowledgeIngestRequest,
        _: TechnicianAccess,
    ) -> list[dict[str, object]]:
        try:
            settings = replace(
                active_settings,
                document_parser=request.parser or active_settings.document_parser,
                allow_ocr=active_settings.allow_ocr if request.ocr is None else request.ocr,
            )
            service = ingestion_service_from_settings(store, settings)
            documents = service.ingest_path(Path(request.path), client_id=request.client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(document) for document in documents]

    @app.get("/knowledge/documents")
    def knowledge_documents(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [asdict(document) for document in store.list_knowledge_documents(client_id=client_id)]

    @app.get("/knowledge/search")
    def knowledge_search(
        _: ViewerAccess,
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

    def _scheduled_job_view(job) -> dict[str, object]:
        return {
            "id": job.id,
            "template_id": job.template_id,
            "cron": job.cron,
            "paused": job.paused,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "client_id": job.client_id,
            "next_run_at": job.next_run_at,
            "params": _safe_json_object(job.params_json),
        }

    return app


def _safe_json_object(payload_json: str) -> dict[str, object]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _scheduled_ticket_id(params: dict[str, object]) -> str:
    ticket_id = params.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        raise HTTPException(status_code=422, detail="scheduled job params must include ticket_id")
    return ticket_id


def _rate_limit_handler(request: Request, exc: Exception) -> Response:
    response = _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))
    current_limit = getattr(request.state, "view_rate_limit", None)
    if current_limit is None:
        return response
    reset_at, _remaining = request.app.state.limiter.limiter.get_window_stats(
        current_limit[0],
        *current_limit[1],
    )
    response.headers["Retry-After"] = str(max(1, int(reset_at - time.time()) + 1))
    return response


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
