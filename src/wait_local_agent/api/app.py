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
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from wait_local_agent.api.founder import (
    FounderNotConfiguredError,
    FounderPackContractError,
    FounderPackUnavailableError,
    FounderUploadConflictError,
    founder_not_configured_handler,
    founder_pack_unavailable_handler,
    founder_privacy_handler,
    founder_upload_conflict_handler,
    launch_passport_error_handler,
)
from wait_local_agent.api.founder import (
    create_router as create_founder_router,
)
from wait_local_agent.api.packs.loader import (
    PackInstallError,
    configure_pack_routes,
    install_pack_tarball,
)
from wait_local_agent.backup import (
    BackupEncryptionError,
    backup_state,
    restore_state,
    run_restore_exercise,
)
from wait_local_agent.collectors import CollectorService, collector_run_result_status, default_registry
from wait_local_agent.config import Settings, load_settings
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_halopsa_approval_request,
    list_connector_statuses,
    list_secret_records,
    update_halopsa_approval_fields,
)
from wait_local_agent.founder_bundle import PrivacyViolation
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.hudu import HuduClient, HuduReadResponse
from wait_local_agent.knowledge import ingestion_service_from_settings
from wait_local_agent.lp_client import (
    LaunchPassportError,
    LaunchPassportForbidden,
    LaunchPassportPayloadTooLarge,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
)
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.rbac import AuthContext, Role, require_role
from wait_local_agent.reports.builders import (
    build_appliance_hardening_report,
    build_restore_evidence_report,
)
from wait_local_agent.reports.hardening_checks import HardeningContext, run_hardening_checks
from wait_local_agent.reports.models import ReportFormat, ReportType
from wait_local_agent.reports.renderers import redact_text, redact_value, report_as_dict
from wait_local_agent.reports.service import ReportService
from wait_local_agent.scheduler import SchedulerManager
from wait_local_agent.security import auth_required
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store, _normalize_client_id
from wait_local_agent.update_channel import UpdateStatusCache, check_for_updates
from wait_local_agent.vault import SecretVault, SecretVaultError
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


class SmartActionInvokeRequest(BaseModel):
    payload: dict[str, object] = Field(default_factory=dict)
    confirm: bool = False
    client_id: str | None = None


class ScheduledJobCreateRequest(BaseModel):
    template_id: str
    cron: str
    params: dict[str, object]


class CollectorConfigRequest(BaseModel):
    config: dict[str, object] = Field(default_factory=dict)
    client_id: str | None = None


class CollectorRunRequest(CollectorConfigRequest):
    confirm: bool = False


class PackInstallRequest(BaseModel):
    tarball_path: str = Field(validation_alias=AliasChoices("tarball_path", "tarball"))
    license_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("license_key", "license"),
    )

    model_config = ConfigDict(populate_by_name=True)


class BackupCreateRequest(BaseModel):
    destination: str
    encrypt: bool = False


class BackupRestoreRequest(BaseModel):
    source: str
    encrypted: bool = False


class HardeningRunRequest(BaseModel):
    backup_paths: list[str] = Field(default_factory=list)


class RestoreExerciseRequest(BaseModel):
    backup_id: str
    encrypted: bool = False


class SecretSetRequest(BaseModel):
    name: str
    value: str


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
    report_service = ReportService(store)
    collector_service = CollectorService(store, default_registry)
    smart_action_service = SmartActionService(store, active_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown()

    app = FastAPI(
        title="WAIT Local Agent",
        version="1.1.1",
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
    app.add_exception_handler(RequestValidationError, _request_validation_error_handler)
    app.add_exception_handler(FounderPackUnavailableError, founder_pack_unavailable_handler)
    app.add_exception_handler(FounderNotConfiguredError, founder_not_configured_handler)
    app.add_exception_handler(FounderPackContractError, _founder_contract_error_handler)
    app.add_exception_handler(FounderUploadConflictError, founder_upload_conflict_handler)
    app.add_exception_handler(PrivacyViolation, founder_privacy_handler)
    app.add_exception_handler(LaunchPassportError, launch_passport_error_handler)
    app.add_exception_handler(LaunchPassportUnauthorized, launch_passport_error_handler)
    app.add_exception_handler(LaunchPassportForbidden, launch_passport_error_handler)
    app.add_exception_handler(LaunchPassportPayloadTooLarge, launch_passport_error_handler)
    app.add_exception_handler(LaunchPassportRequestError, launch_passport_error_handler)
    app.add_middleware(SlowAPIMiddleware)
    configure_pack_routes(
        app,
        active_settings,
        route_dependencies=[Depends(require_role(Role.VIEWER))],
    )
    app.include_router(create_founder_router())

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

    @app.post("/update-check")
    def update_check(_: AdminAccess) -> dict[str, object]:
        return check_for_updates(active_settings).to_dict()

    @app.get("/packs")
    def packs(_: ViewerAccess) -> list[dict[str, object]]:
        registry = app.state.pack_registry
        return [
            {
                "name": status.name,
                "version": status.version,
                "locked": status.locked,
                "requires_license": status.requires_license,
            }
            for status in registry.statuses
        ]

    @app.get("/packs/status")
    def pack_status(_: ViewerAccess) -> list[dict[str, object]]:
        registry = app.state.pack_registry
        return [asdict(status) for status in registry.statuses]

    @app.post("/packs/install")
    def pack_install(payload: PackInstallRequest, _: AdminAccess) -> dict[str, object]:
        try:
            result = install_pack_tarball(
                Path(payload.tarball_path),
                license_key=payload.license_key,
                settings=active_settings,
            )
        except PackInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail="pack tarball could not be read") from exc
        return {
            "pack_name": result.pack_name,
            "version": result.version,
            "files": len(result.extracted_files),
            "license_stored_in_vault": result.license_stored_in_vault,
        }

    @app.get("/tickets")
    def tickets(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [asdict(ticket) for ticket in store.list_tickets(client_id=client_id)]

    @app.get("/smart-actions")
    def smart_actions(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(manifest) for manifest in smart_action_service.list()]

    @app.get("/smart-actions/runs")
    def smart_action_runs(
        context: ViewerAccess, client_id: str | None = None
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        return [
            _smart_action_run_view(run)
            for run in smart_action_service.store.list_smart_action_runs(client_id=scoped_client_id)
        ]

    @app.get("/smart-actions/runs/{run_id}")
    def smart_action_run_detail(
        run_id: int, context: ViewerAccess, client_id: str | None = None
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="smart action run not found")
        run = smart_action_service.store.get_smart_action_run(run_id, client_id=scoped_client_id)
        if run is None:
            raise HTTPException(status_code=404, detail="smart action run not found")
        return _smart_action_run_view(run)

    @app.get("/smart-actions/{action_id}")
    def smart_action_detail(action_id: str, _: ViewerAccess) -> dict[str, object]:
        try:
            return asdict(smart_action_service.describe(action_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="smart action not found") from exc

    @app.post("/smart-actions/{action_id}/invoke")
    def invoke_smart_action(
        action_id: str,
        payload: SmartActionInvokeRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            scoped_client_id = _smart_action_client_scope(context, payload.client_id)
            if context.role < Role.ADMIN and scoped_client_id is None:
                raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
            result = smart_action_service.invoke(
                action_id,
                payload.payload,
                context.approver_id or "api",
                confirm=payload.confirm,
                client_id=scoped_client_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="smart action not found") from exc
        return asdict(result)

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
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _approval_client_scope(context, client_id)
        return [
            _approval_view(request)
            for request in store.list_approval_requests(client_id=scoped_client_id)
        ]

    @app.get("/approval-requests/{request_id}")
    def approval_request_detail(request_id: int, context: ViewerAccess) -> dict[str, object]:
        request = store.get_approval_request(request_id)
        if request is None or not _approval_in_scope(context, request):
            raise HTTPException(status_code=404, detail="approval request not found")
        return _approval_view(request)

    @app.patch("/approval-requests/{request_id}/payload")
    def update_approval_payload(
        request_id: int,
        request: ApprovalPayloadPatchRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_in_scope(context, approval):
                raise KeyError(request_id)
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
            existing_approval = store.get_approval_request(request_id)
            if existing_approval is None or not _approval_in_scope(context, existing_approval):
                raise KeyError(request_id)
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
            return _approval_view(approval)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/collectors/modules")
    def collector_modules(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(manifest) for manifest in collector_service.list_modules()]

    @app.post("/collectors/modules/{module_id}/validate")
    def collector_validate(
        module_id: str,
        payload: CollectorConfigRequest,
        _: ViewerAccess,
    ) -> dict[str, object]:
        try:
            return asdict(collector_service.validate(module_id, payload.config))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector module not found") from exc

    @app.post("/collectors/modules/{module_id}/preview")
    def collector_preview(
        module_id: str,
        payload: CollectorConfigRequest,
        _: ViewerAccess,
    ) -> dict[str, object]:
        try:
            return asdict(collector_service.preview(module_id, payload.config))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector module not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/collectors/modules/{module_id}/run")
    def collector_run(
        module_id: str,
        payload: CollectorRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            run = collector_service.run(
                module_id,
                payload.config,
                confirm=payload.confirm,
                client_id=payload.client_id,
                actor_id=context.approver_id,
            )
            return {**asdict(run), "result_status": collector_run_result_status(run)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector module not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/collectors/runs")
    def collector_runs(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {**asdict(run), "result_status": collector_run_result_status(run)}
            for run in store.list_collector_runs(client_id=client_id)
        ]

    @app.get("/collectors/runs/{run_id}")
    def collector_run_detail(run_id: int, _: ViewerAccess) -> dict[str, object]:
        run = store.get_collector_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="collector run not found")
        return {
            **asdict(run),
            "result_status": collector_run_result_status(run),
            "assets": [asdict(asset) for asset in store.list_canonical_assets(run_id=run_id)],
            "observations": [
                asdict(observation) for observation in store.list_asset_observations(run_id=run_id)
            ],
            "config_snapshots": [
                asdict(snapshot) for snapshot in store.list_config_snapshots(run_id=run_id)
            ],
            "config_diffs": [asdict(diff) for diff in store.list_config_diffs(run_id=run_id)],
            "restore_exercises": [
                asdict(exercise) for exercise in store.list_restore_exercises(run_id=run_id)
            ],
        }

    @app.post("/collectors/runs/{run_id}/export")
    def collector_run_export(
        run_id: int,
        context: ViewerAccess,
        report_type: ReportType = ReportType.COLLECTOR_BUNDLE,
    ) -> dict[str, object]:
        try:
            report = collector_service.export_report(
                run_id,
                report_type,
                created_by=context.approver_id or "system",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="collector run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report_as_dict(report)

    @app.get("/reports")
    def reports(
        _: ViewerAccess,
        report_type: ReportType | None = None,
        client_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, object]]:
        stored = report_service.list_reports(
            report_type=report_type,
            client_id=client_id,
            project_id=project_id,
        )
        return [report_as_dict(report) for report in stored]

    @app.get("/reports/{report_id}")
    def report_detail(report_id: str, _: ViewerAccess) -> dict[str, object]:
        report = report_service.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return report_as_dict(report)

    @app.get("/reports/{report_id}/export")
    def report_export(
        report_id: str,
        _: ViewerAccess,
        export_format: Literal["json", "markdown"] = "json",
    ) -> Response:
        try:
            rendered = report_service.export_report(report_id, ReportFormat(export_format))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="report not found") from exc
        media_type = "application/json" if export_format == "json" else "text/markdown"
        extension = "json" if export_format == "json" else "md"
        return Response(
            rendered,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="wait-report-{report_id}.{extension}"'
            },
        )

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
    def event_history(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [asdict(event) for event in store.list_event_history(client_id=client_id)]

    @app.get("/connectors")
    def connectors(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(status) for status in list_connector_statuses(active_settings)]

    @app.get("/secrets")
    def secrets(_: AdminAccess) -> list[dict[str, object]]:
        return [asdict(secret) for secret in list_secret_records(active_settings)]

    @app.post("/secrets")
    def set_secret(payload: SecretSetRequest, _: AdminAccess) -> dict[str, str]:
        try:
            SecretVault.initialize(active_settings.vault_path).set(payload.name, payload.value)
        except (SecretVaultError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"name": payload.name, "status": "stored"}

    @app.post("/backups")
    def create_backup(payload: BackupCreateRequest, _: AdminAccess) -> dict[str, object]:
        try:
            path = backup_state(
                store,
                Path(payload.destination),
                encrypt=payload.encrypt,
                settings=active_settings,
            )
        except BackupEncryptionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail="backup destination could not be written") from exc
        return {"backup": str(path), "encrypted": payload.encrypt}

    @app.post("/backups/restore")
    def restore_backup(payload: BackupRestoreRequest, _: AdminAccess) -> dict[str, object]:
        try:
            path = restore_state(
                store,
                Path(payload.source),
                encrypted=payload.encrypted,
                settings=active_settings,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="backup source not found") from exc
        except BackupEncryptionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail="backup source could not be restored") from exc
        return {"restored": str(path), "encrypted": payload.encrypted}

    @app.post("/hardening/runs")
    def create_hardening_run(payload: HardeningRunRequest, context: AdminAccess) -> dict[str, object]:
        store.add_audit_event("hardening.run_requested", "hardening", "admin requested hardening checks")
        backup_paths = tuple(Path(item) for item in payload.backup_paths)
        if not backup_paths:
            backup_paths = tuple(
                path
                for path in active_settings.data_path.parent.glob("*")
                if path.is_file() and path != active_settings.data_path
            )
        hardening_context = HardeningContext.from_settings(
            active_settings,
            store=store,
            backup_paths=backup_paths,
            audit_event_count=len(store.list_audit_events()),
        )
        run = run_hardening_checks(hardening_context, store=store)
        if run.id is None:
            raise HTTPException(status_code=500, detail="hardening run was not persisted")
        sections, metadata = build_appliance_hardening_report(store, run.id)
        report = report_service.create_report(
            ReportType.APPLIANCE_HARDENING,
            f"Appliance Hardening Evidence {run.id}",
            sections,
            created_by=context.approver_id or "system",
            project_id=f"hardening-run-{run.id}",
            metadata=metadata,
        )
        store.add_audit_event("hardening.run_completed", str(run.id), run.status)
        return {"run": asdict(run), "report": report_as_dict(report)}

    @app.get("/hardening/runs")
    def list_hardening_runs(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(run) for run in store.list_hardening_runs()]

    @app.post("/backup/restore-exercises")
    def create_restore_exercise(
        payload: RestoreExerciseRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        store.add_audit_event(
            "backup.restore_exercise_requested",
            payload.backup_id,
            "admin requested restore exercise",
        )
        try:
            result = run_restore_exercise(
                payload.backup_id,
                store=store,
                settings=active_settings,
                encrypted=payload.encrypted,
            )
        except OSError as exc:
            raise HTTPException(status_code=400, detail="restore exercise could not be started") from exc
        sections, metadata = build_restore_evidence_report(store)
        report = report_service.create_report(
            ReportType.RESTORE_EVIDENCE,
            "Restore Evidence",
            sections,
            created_by=context.approver_id or "system",
            project_id=f"restore-exercise-{result.exercise_id}",
            metadata=metadata,
        )
        return {"exercise": asdict(result), "report": report_as_dict(report)}

    @app.get("/backup/restore-exercises")
    def list_restore_exercises(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(exercise) for exercise in store.list_restore_exercises()]

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
        return _halopsa_draft_view(draft)

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
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_in_scope(context, approval):
                raise KeyError(request_id)
            return _approval_view(execute_halopsa_approval_request(store, halopsa_client, request_id))
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
        ticket = store.get_ticket(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        params = dict(request.params)
        raw_client_id = params.get("client_id")
        normalized_client_id = (
            _normalize_client_id(raw_client_id) if raw_client_id is None or isinstance(raw_client_id, str) else None
        )
        if normalized_client_id is None and ticket.client_id:
            params["client_id"] = ticket.client_id
        try:
            scheduled_job = scheduler.register(
                request.template_id,
                request.cron,
                params,
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
    def workflow_run_detail(run_id: int, context: ViewerAccess) -> dict[str, object]:
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
            "approval_request": (
                _approval_view(approval)
                if approval is not None and _approval_in_scope(context, approval)
                else None
            ),
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
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        try:
            settings = replace(
                active_settings,
                vector_backend=backend or active_settings.vector_backend,
            )
            search_backend = search_backend_from_settings(settings, store)
            return [asdict(chunk) for chunk in search_backend.search(q, limit=limit, client_id=client_id)]
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
        view = asdict(request)
        view["payload_json"] = _redact_json_text(request.payload_json)
        view["execution_result_json"] = _redact_json_text(request.execution_result_json)
        view["comment"] = redact_text(request.comment)
        view["payload"] = _redact_payload(payload)
        view["output"] = _safe_redacted_json_object(request.execution_result_json)
        return {
            **view,
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


def _smart_action_run_view(run) -> dict[str, object]:
    output = redact_value(_safe_json_object(run.output_json))
    evidence = redact_value(_safe_json_list(run.evidence_json))
    return {
        "id": run.id,
        "action_id": run.action_id,
        "actor": run.actor,
        "status": run.status,
        "payload_digest": run.payload_digest,
        "output": output,
        "evidence": evidence,
        "approval_id": run.approval_id,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "client_id": run.client_id,
    }


def _approval_client_scope(context: AuthContext, requested_client_id: str | None) -> str | None:
    """Approval scope preserves unbound filters intentionally, unlike smart-action scope."""

    if context.role >= Role.ADMIN:
        return _normalize_client_id(requested_client_id)
    bound_client_id = _normalize_client_id(context.client_id)
    if bound_client_id is None:
        return _normalize_client_id(requested_client_id)
    return bound_client_id


def _approval_in_scope(context: AuthContext, approval) -> bool:
    scoped_client_id = _approval_client_scope(context, None)
    approval_client_id = _normalize_client_id(approval.client_id)
    return (
        scoped_client_id is None
        or approval_client_id is None
        or approval_client_id == scoped_client_id
    )


def _smart_action_client_scope(context: AuthContext, requested_client_id: str | None) -> str | None:
    """Return the authenticated tenant scope; only admins may choose a filter."""

    if context.role >= Role.ADMIN:
        return _normalize_client_id(requested_client_id)
    return _normalize_client_id(context.client_id)


def _halopsa_draft_view(draft) -> dict[str, object]:
    payload = _safe_json_object(draft.payload_json)
    return {
        **asdict(draft),
        "payload_json": _redact_json_text(draft.payload_json),
        "payload": _redact_payload(payload),
    }


def _safe_json_object(payload_json: str) -> dict[str, object]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_json_list(payload_json: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _redact_json_text(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return "[redacted]"
    return json.dumps(redact_value(payload), sort_keys=True, separators=(",", ":"))


def _safe_redacted_json_object(payload_json: str) -> dict[str, object]:
    return cast(dict[str, object], redact_value(_safe_json_object(payload_json)))


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


def _founder_contract_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": str(cast(FounderPackContractError, exc))},
    )


def _request_validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    sensitive_fields: set[str]
    if request.url.path == "/secrets":
        sensitive_fields = {"value"}
    elif request.url.path == "/packs/install":
        sensitive_fields = {"license", "license_key"}
    else:
        sensitive_fields = set()

    errors: list[dict[str, object]] = []
    for error in validation_error.errors():
        redacted = dict(error)
        location = error.get("loc")
        if isinstance(location, tuple) and location and str(location[-1]) in sensitive_fields:
            redacted["input"] = "[redacted]"
        elif "input" in error:
            redacted["input"] = _redact_request_input(error["input"], sensitive_fields)
        errors.append(redacted)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


def _redact_request_input(value: object, sensitive_fields: set[str]) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if str(key).lower() in sensitive_fields
            else _redact_request_input(item, sensitive_fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_request_input(item, sensitive_fields) for item in value]
    return "[redacted]" if sensitive_fields else value


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
