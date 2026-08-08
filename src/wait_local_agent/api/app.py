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

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from wait_local_agent.agents import AgentDefinitionError, AgentService
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
from wait_local_agent.autotask import AutotaskClient, AutotaskReadResponse
from wait_local_agent.backup import (
    BackupEncryptionError,
    backup_state,
    restore_state,
    run_restore_exercise,
)
from wait_local_agent.collectors import (
    CollectorService,
    collector_run_collection_scope,
    collector_run_result_status,
    default_registry,
)
from wait_local_agent.config import Settings, load_settings
from wait_local_agent.confluence import ConfluenceClient, ConfluenceReadResponse
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_halopsa_approval_request,
    list_connector_statuses,
    list_secret_records,
    update_halopsa_approval_fields,
)
from wait_local_agent.connectwise import ConnectWiseClient, ConnectWiseReadResponse
from wait_local_agent.event_dispatch import EventDispatcher, EventDispatchError
from wait_local_agent.founder_bundle import PrivacyViolation
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.hudu import HuduClient, HuduReadResponse
from wait_local_agent.itglue import ItGlueClient, ItGlueReadResponse
from wait_local_agent.knowledge import ingestion_service_from_settings
from wait_local_agent.lp_client import (
    LaunchPassportError,
    LaunchPassportForbidden,
    LaunchPassportPayloadTooLarge,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
)
from wait_local_agent.models import AgentDefinition
from wait_local_agent.observability import (
    ESTIMATED_MINUTES_SAVED_DERIVATION,
    build_analytics_summary,
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
from wait_local_agent.servicenow import ServiceNowClient, ServiceNowReadResponse
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store, _normalize_client_id
from wait_local_agent.syncro import SyncroClient, SyncroReadResponse
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


class TemplateGalleryCreateRequest(BaseModel):
    source_template_id: str
    provenance: str = Field(min_length=1, max_length=1000)
    display_name: str | None = Field(default=None, max_length=120)
    client_id: str | None = None


class SmartActionInvokeRequest(BaseModel):
    payload: dict[str, object] = Field(default_factory=dict)
    confirm: bool = False
    client_id: str | None = None


class AgentStepRequest(BaseModel):
    tool_id: str
    payload: dict[str, object] = Field(default_factory=dict)


class AgentDefinitionRequest(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    trigger: Literal["manual", "scheduled", "event"] = "manual"
    entity_type: Literal["ticket"] = "ticket"
    filters: dict[str, object] = Field(default_factory=dict)
    enabled_tools: list[str]
    steps: list[AgentStepRequest]
    max_steps: int = Field(default=8, ge=1, le=8)
    execution_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    client_id: str | None = None
    run_once_per_entity: bool = True
    depends_on_agent_ids: list[str] = Field(default_factory=list)


class AgentRunStartRequest(BaseModel):
    entity_id: str
    input: dict[str, object] = Field(default_factory=dict)
    client_id: str | None = None


class AgentBackfillCreateRequest(BaseModel):
    agent_id: str
    entity_ids: list[str] = Field(min_length=1, max_length=100)
    input: dict[str, object] = Field(default_factory=dict)
    client_id: str | None = None


class EventIngestRequest(BaseModel):
    event_type: str
    entity_type: Literal["ticket"] = "ticket"
    entity_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = None
    client_id: str | None = None


class ScheduledJobCreateRequest(BaseModel):
    template_id: str | None = None
    agent_id: str | None = None
    entity_id: str | None = None
    cron: str = ""
    schedule_type: Literal["cron", "interval", "once"] = "cron"
    interval_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    run_at: str | None = None
    params: dict[str, object] = Field(default_factory=dict)


class ScheduledJobRescheduleRequest(BaseModel):
    cron: str = ""
    schedule_type: Literal["cron", "interval", "once"] = "cron"
    interval_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    run_at: str | None = None


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
    service = TicketIntelligenceService(
        store=store,
        settings=active_settings,
        provider=provider_from_settings(active_settings),
    )
    halopsa_client = HaloPSAClient(active_settings)
    hudu_client = HuduClient(active_settings)
    connectwise_client = ConnectWiseClient(active_settings)
    syncro_client = SyncroClient(active_settings)
    servicenow_client = ServiceNowClient(active_settings)
    autotask_client = AutotaskClient(active_settings)
    itglue_client = ItGlueClient(active_settings)
    confluence_client = ConfluenceClient(active_settings)
    update_status_cache = UpdateStatusCache(ttl_seconds=3600.0)
    report_service = ReportService(store)
    collector_service = CollectorService(store, default_registry)
    smart_action_service = SmartActionService(
        store,
        active_settings,
        collector_service=collector_service,
        halopsa_client=halopsa_client,
        hudu_client=hudu_client,
    )
    agent_service = AgentService(store, active_settings, smart_action_service)
    event_dispatcher = EventDispatcher(store, agent_service)
    scheduler = SchedulerManager(
        store,
        enabled=active_settings.scheduler_enabled,
        agent_service=agent_service,
    )

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
            "syncro_configured": bool(
                active_settings.syncro_base_url and active_settings.syncro_api_token
            ),
            "servicenow_configured": bool(
                active_settings.servicenow_base_url
                and active_settings.servicenow_username
                and active_settings.servicenow_password
            ),
            "autotask_configured": bool(
                active_settings.autotask_base_url
                and active_settings.autotask_username
                and active_settings.autotask_secret
                and active_settings.autotask_integration_code
            ),
            "itglue_configured": bool(
                active_settings.itglue_base_url and active_settings.itglue_api_key
            ),
            "confluence_configured": bool(
                active_settings.confluence_base_url
                and active_settings.confluence_email
                and active_settings.confluence_api_token
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

    @app.get("/tools")
    def tools(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(tool) for tool in agent_service.list_tools()]

    @app.get("/agents")
    def agents(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        return [
            _agent_definition_view(definition)
            for definition in agent_service.list_definitions(scoped_client_id)
        ]

    @app.post("/agents")
    def create_agent(
        payload: AgentDefinitionRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            definition = agent_service.create(
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                trigger=payload.trigger,
                entity_type=payload.entity_type,
                filters=payload.filters,
                enabled_tools=payload.enabled_tools,
                steps=[step.model_dump() for step in payload.steps],
                max_steps=payload.max_steps,
                execution_timeout_seconds=payload.execution_timeout_seconds,
                client_id=scoped_client_id,
                run_once_per_entity=payload.run_once_per_entity,
                depends_on_agent_ids=payload.depends_on_agent_ids,
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _agent_definition_view(definition)

    @app.get("/agents/{agent_id}")
    def agent_detail(agent_id: str, context: ViewerAccess, client_id: str | None = None) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent not found")
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_definition_view(definition)

    @app.get("/agents/{agent_id}/revisions")
    def agent_revisions(
        agent_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            return []
        return [
            _agent_revision_view(revision)
            for revision in store.list_agent_definition_revisions(agent_id, definition.client_id)
        ]

    @app.get("/agents/{agent_id}/revisions/{version}/diff/{other_version}")
    def agent_revision_diff(
        agent_id: str,
        version: int,
        other_version: int,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent revision not found")
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent revision not found")
        left = store.get_agent_definition_revision(agent_id, version, definition.client_id)
        right = store.get_agent_definition_revision(agent_id, other_version, definition.client_id)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="agent revision not found")
        return _agent_revision_diff_view(left, right)

    @app.post("/agents/{agent_id}/revisions/{version}/restore")
    def restore_agent_revision(
        agent_id: str,
        version: int,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent not found")
        existing = agent_service.get(agent_id, scoped_client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="agent not found")
        revision = store.get_agent_definition_revision(agent_id, version, existing.client_id)
        if revision is None:
            raise HTTPException(status_code=404, detail="agent revision not found")
        try:
            payload = AgentDefinitionRequest.model_validate(_safe_json_object(revision.definition_json))
            restored = agent_service.update(
                existing,
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                trigger=payload.trigger,
                entity_type=payload.entity_type,
                filters=payload.filters,
                enabled_tools=payload.enabled_tools,
                steps=[step.model_dump() for step in payload.steps],
                max_steps=payload.max_steps,
                execution_timeout_seconds=payload.execution_timeout_seconds,
                run_once_per_entity=payload.run_once_per_entity,
                depends_on_agent_ids=payload.depends_on_agent_ids,
            )
        except (AgentDefinitionError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail="agent revision is no longer valid") from exc
        return _agent_definition_view(restored)

    @app.put("/agents/{agent_id}")
    def update_agent(
        agent_id: str,
        payload: AgentDefinitionRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent not found")
        existing = agent_service.get(agent_id, scoped_client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if payload.client_id is not None and _normalize_client_id(payload.client_id) != existing.client_id:
            raise HTTPException(status_code=409, detail="agent tenant scope cannot be changed")
        try:
            updated = agent_service.update(
                existing,
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                trigger=payload.trigger,
                entity_type=payload.entity_type,
                filters=payload.filters,
                enabled_tools=payload.enabled_tools,
                steps=[step.model_dump() for step in payload.steps],
                max_steps=payload.max_steps,
                execution_timeout_seconds=payload.execution_timeout_seconds,
                run_once_per_entity=payload.run_once_per_entity,
                depends_on_agent_ids=payload.depends_on_agent_ids,
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _agent_definition_view(updated)

    @app.post("/agents/{agent_id}/run")
    def run_agent(
        agent_id: str,
        payload: AgentRunStartRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        definition = agent_service.get(agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if definition.client_id is None and scoped_client_id is not None:
            definition = replace(definition, client_id=scoped_client_id)
        try:
            result = agent_service.run(
                definition,
                entity_id=payload.entity_id,
                actor=context.approver_id or "api",
                input_payload=payload.input,
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(result)

    def _backfill_scope(context: AuthContext, requested_client_id: str | None) -> str | None:
        scoped_client_id = _smart_action_client_scope(context, requested_client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        return scoped_client_id

    def _process_backfill(
        backfill,
        definition,
        context: AuthContext,
        scoped_client_id: str | None,
    ):
        entity_ids = [
            item for item in _safe_json_values(backfill.entity_ids_json) if isinstance(item, str)
        ]
        input_payload = _safe_json_object(backfill.input_json)
        run_ids = [
            item for item in _safe_json_values(backfill.run_ids_json)
            if isinstance(item, int) and not isinstance(item, bool)
        ]
        failed_entity_ids = [
            item
            for item in _safe_json_values(backfill.failed_entity_ids_json)
            if isinstance(item, str)
        ]
        errors = [backfill.error_detail] if backfill.error_detail else []
        if definition.client_id is None and scoped_client_id is not None:
            definition = replace(definition, client_id=scoped_client_id)
        store.update_agent_backfill(
            backfill.id or 0,
            status="running",
            next_index=backfill.next_index,
            processed_count=backfill.processed_count,
            succeeded_count=backfill.succeeded_count,
            failed_count=backfill.failed_count,
            run_ids=run_ids,
            failed_entity_ids=failed_entity_ids,
            error_detail="; ".join(errors),
        )
        processed_count = backfill.processed_count
        succeeded_count = backfill.succeeded_count
        failed_count = backfill.failed_count
        for index in range(backfill.next_index, len(entity_ids)):
            entity_id = entity_ids[index]
            try:
                result = agent_service.run(
                    definition,
                    entity_id=entity_id,
                    actor=backfill.actor or context.approver_id or "api",
                    input_payload=input_payload,
                )
                if result.run_id:
                    run_ids.append(result.run_id)
                if result.status in {"completed", "pending_approval"}:
                    succeeded_count += 1
                else:
                    failed_count += 1
                    failed_entity_ids.append(entity_id)
                    errors.append(f"{entity_id}: agent run status {result.status}")
            except Exception as exc:  # noqa: BLE001 - continue independent entities
                failed_count += 1
                failed_entity_ids.append(entity_id)
                errors.append(redact_text(f"{entity_id}: {exc}"))
            processed_count += 1
            store.update_agent_backfill(
                backfill.id or 0,
                status="running",
                next_index=index + 1,
                processed_count=processed_count,
                succeeded_count=succeeded_count,
                failed_count=failed_count,
                run_ids=run_ids,
                failed_entity_ids=failed_entity_ids,
                error_detail="; ".join(errors),
            )
        final_status = "completed_with_errors" if failed_entity_ids else "completed"
        return store.update_agent_backfill(
            backfill.id or 0,
            status=final_status,
            next_index=len(entity_ids),
            processed_count=processed_count,
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            run_ids=run_ids,
            failed_entity_ids=failed_entity_ids,
            error_detail="; ".join(errors),
        )

    @app.post("/agent-backfills")
    def create_agent_backfill(
        payload: AgentBackfillCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _backfill_scope(context, payload.client_id)
        if len(set(payload.entity_ids)) != len(payload.entity_ids):
            raise HTTPException(status_code=422, detail="entity_ids must not contain duplicates")
        definition = agent_service.get(payload.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        for entity_id in payload.entity_ids:
            if store.get_ticket(entity_id, client_id=scoped_client_id) is None:
                raise HTTPException(status_code=404, detail=f"ticket not found: {entity_id}")
        backfill = store.create_agent_backfill(
            payload.agent_id,
            payload.entity_ids,
            payload.input,
            actor=context.approver_id or "api",
            client_id=scoped_client_id,
        )
        return _agent_backfill_view(backfill)

    @app.get("/agent-backfills")
    def agent_backfills(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _backfill_scope(context, client_id)
        return [_agent_backfill_view(item) for item in store.list_agent_backfills(scoped_client_id)]

    @app.get("/agent-backfills/{backfill_id}")
    def agent_backfill_detail(backfill_id: int, context: ViewerAccess) -> dict[str, object]:
        scoped_client_id = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scoped_client_id)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        return _agent_backfill_view(backfill)

    @app.post("/agent-backfills/{backfill_id}/run")
    def run_agent_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scoped_client_id = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scoped_client_id)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status not in {"queued", "paused"}:
            raise HTTPException(status_code=409, detail="agent backfill is not runnable in its current state")
        definition = agent_service.get(backfill.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_backfill_view(_process_backfill(backfill, definition, context, scoped_client_id))

    @app.post("/agent-backfills/{backfill_id}/pause")
    def pause_agent_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scoped_client_id = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scoped_client_id)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status != "queued":
            raise HTTPException(status_code=409, detail="only queued backfills can be paused")
        return _agent_backfill_view(
            store.update_agent_backfill(
                backfill_id,
                status="paused",
                next_index=backfill.next_index,
                processed_count=backfill.processed_count,
                succeeded_count=backfill.succeeded_count,
                failed_count=backfill.failed_count,
                run_ids=[
                    item for item in _safe_json_values(backfill.run_ids_json)
                    if isinstance(item, int) and not isinstance(item, bool)
                ],
                failed_entity_ids=[
                    item for item in _safe_json_values(backfill.failed_entity_ids_json)
                    if isinstance(item, str)
                ],
                error_detail=backfill.error_detail,
            )
        )

    @app.post("/agent-backfills/{backfill_id}/cancel")
    def cancel_agent_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scoped_client_id = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scoped_client_id)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status in {"completed", "completed_with_errors", "cancelled"}:
            raise HTTPException(status_code=409, detail="agent backfill is already terminal")
        return _agent_backfill_view(
            store.update_agent_backfill(
                backfill_id,
                status="cancelled",
                next_index=backfill.next_index,
                processed_count=backfill.processed_count,
                succeeded_count=backfill.succeeded_count,
                failed_count=backfill.failed_count,
                run_ids=[],
                failed_entity_ids=[],
                error_detail=backfill.error_detail,
            )
        )

    @app.post("/agent-backfills/{backfill_id}/rerun-failed")
    def rerun_failed_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scoped_client_id = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scoped_client_id)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        failed_entity_ids = [
            item for item in _safe_json_values(backfill.failed_entity_ids_json)
            if isinstance(item, str)
        ]
        if not failed_entity_ids:
            raise HTTPException(status_code=409, detail="agent backfill has no failed entities")
        reset = store.reset_agent_backfill_failed(backfill_id, failed_entity_ids)
        definition = agent_service.get(reset.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_backfill_view(_process_backfill(reset, definition, context, scoped_client_id))

    def _definition_for_agent_run(run) -> AgentDefinition | None:
        definition = agent_service.get(run.agent_id, run.client_id)
        if definition is None:
            definition = agent_service.get(run.agent_id)
        if definition is None:
            return None
        if definition.client_id is not None and definition.client_id != run.client_id:
            return None
        if definition.client_id is None and run.client_id is not None:
            return replace(definition, client_id=run.client_id)
        return definition

    @app.get("/agent-runs")
    def agent_runs(context: ViewerAccess, client_id: str | None = None) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        return [_agent_run_view(run) for run in store.list_agent_runs(scoped_client_id)]

    @app.get("/agent-runs/{run_id}")
    def agent_run_detail(run_id: int, context: ViewerAccess, client_id: str | None = None) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        run = store.get_agent_run(run_id, scoped_client_id)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        view = _agent_run_view(run)
        definition = _definition_for_agent_run(run)
        if definition is not None and run.revision_version is not None:
            revision = store.get_agent_definition_revision(
                run.agent_id,
                run.revision_version,
                definition.client_id,
            )
            if revision is None and definition.client_id == run.client_id:
                revision = store.get_agent_definition_revision(
                    run.agent_id,
                    run.revision_version,
                    None,
                )
            if revision is not None:
                view["definition_revision"] = _agent_revision_view(revision)
        return view

    @app.post("/agent-runs/{run_id}/resume")
    def resume_agent(run_id: int, context: TechnicianAccess, client_id: str | None = None) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        run = store.get_agent_run(run_id, scoped_client_id)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        definition = _definition_for_agent_run(run)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent definition not found")
        try:
            result = agent_service.resume(
                definition,
                run,
                approver=context.approver_id or "api",
                approver_role=context.role,
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return asdict(result)

    @app.post("/agent-runs/{run_id}/cancel")
    def cancel_agent_run(run_id: int, context: TechnicianAccess, client_id: str | None = None) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        run = store.get_agent_run(run_id, scoped_client_id)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        definition = _definition_for_agent_run(run)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent definition not found")
        try:
            result = agent_service.cancel(
                definition,
                run,
                actor=context.approver_id or "api",
                approver_role=context.role,
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return asdict(result)

    @app.post("/agent-runs/{run_id}/retry")
    def retry_agent_run(run_id: int, context: TechnicianAccess, client_id: str | None = None) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        run = store.get_agent_run(run_id, scoped_client_id)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        definition = _definition_for_agent_run(run)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent definition not found")
        try:
            result = agent_service.retry(
                definition,
                run,
                actor=context.approver_id or "api",
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"retry_of_run_id": run.id, **asdict(result)}

    @app.post("/automation/events")
    @limiter.limit(active_settings.rate_limit_general)
    def ingest_automation_event(
        request: Request,
        payload: EventIngestRequest,
        context: TechnicianAccess,
        idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
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
            )
        except EventDispatchError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="event entity not found") from exc
        return _event_dispatch_view(result)

    @app.get("/automation/event-deliveries")
    def event_deliveries(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        return [_event_delivery_view(delivery) for delivery in store.list_event_deliveries(scoped_client_id)]

    @app.get("/automation/event-deliveries/{delivery_id}")
    def event_delivery_detail(delivery_id: int, context: ViewerAccess) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="event delivery not found")
        delivery = store.get_event_delivery(delivery_id, scoped_client_id)
        if delivery is None:
            raise HTTPException(status_code=404, detail="event delivery not found")
        return _event_delivery_view(delivery)

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
        context: ViewerAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        try:
            return asdict(
                collector_service.preview(
                    module_id,
                    payload.config,
                    client_id=scoped_client_id,
                )
            )
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
            return {
                **asdict(run),
                "result_status": collector_run_result_status(run),
                "collection_scope": collector_run_collection_scope(run),
            }
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
            {
                **asdict(run),
                "result_status": collector_run_result_status(run),
                "collection_scope": collector_run_collection_scope(run),
            }
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
            "collection_scope": collector_run_collection_scope(run),
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

    @app.get("/connectors/connectwise/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = connectwise_client.health()
        _audit_connectwise_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/connectwise/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_tickets(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        conditions: str | None = None,
    ) -> dict[str, object]:
        response = connectwise_client.list_tickets(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.connectwise_page_size
            ),
            conditions=conditions,
        )
        return _connectwise_response("tickets.list", response)

    @app.get("/connectors/connectwise/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_ticket(
        ticket_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = connectwise_client.get_ticket(ticket_id)
        return _connectwise_response("tickets.get", response)

    @app.get("/connectors/connectwise/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_companies(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        conditions: str | None = None,
    ) -> dict[str, object]:
        response = connectwise_client.list_companies(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.connectwise_page_size
            ),
            conditions=conditions,
        )
        return _connectwise_response("companies.list", response)

    @app.get("/connectors/syncro/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = syncro_client.health()
        _audit_syncro_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/syncro/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_tickets(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        query: str | None = None,
        customer_id: str | None = None,
        status: str | None = None,
        since_updated_at: str | None = None,
    ) -> dict[str, object]:
        response = syncro_client.list_tickets(
            page=page,
            query=query,
            customer_id=customer_id,
            status=status,
            since_updated_at=since_updated_at,
        )
        return _syncro_response("tickets.list", response)

    @app.get("/connectors/syncro/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_ticket(ticket_id: str, request: Request, _: ViewerAccess) -> dict[str, object]:
        response = syncro_client.get_ticket(ticket_id)
        return _syncro_response("tickets.get", response)

    @app.get("/connectors/syncro/customers")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_customers(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        query: str | None = None,
        business_name: str | None = None,
    ) -> dict[str, object]:
        response = syncro_client.list_customers(
            page=page,
            query=query,
            business_name=business_name,
        )
        return _syncro_response("customers.list", response)

    @app.get("/connectors/syncro/customers/{customer_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_customer(
        customer_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = syncro_client.get_customer(customer_id)
        return _syncro_response("customers.get", response)

    @app.get("/connectors/servicenow/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = servicenow_client.health()
        _audit_servicenow_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/servicenow/incidents")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_incidents(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        query: str | None = None,
    ) -> dict[str, object]:
        response = servicenow_client.list_incidents(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.servicenow_page_size
            ),
            query=query,
        )
        return _servicenow_response("incidents.list", response)

    @app.get("/connectors/servicenow/incidents/{sys_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_incident(
        sys_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = servicenow_client.get_incident(sys_id)
        return _servicenow_response("incidents.get", response)

    @app.get("/connectors/servicenow/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_companies(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        query: str | None = None,
    ) -> dict[str, object]:
        response = servicenow_client.list_companies(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.servicenow_page_size
            ),
            query=query,
        )
        return _servicenow_response("companies.list", response)

    @app.get("/connectors/servicenow/companies/{sys_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_company(
        sys_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = servicenow_client.get_company(sys_id)
        return _servicenow_response("companies.get", response)

    @app.get("/connectors/autotask/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = autotask_client.health()
        _audit_autotask_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/autotask/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_tickets(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = autotask_client.list_tickets(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.autotask_page_size
            ),
        )
        return _autotask_response("tickets.list", response)

    @app.get("/connectors/autotask/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_ticket(
        ticket_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = autotask_client.get_ticket(ticket_id)
        return _autotask_response("tickets.get", response)

    @app.get("/connectors/autotask/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_companies(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = autotask_client.list_companies(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.autotask_page_size
            ),
        )
        return _autotask_response("companies.list", response)

    @app.get("/connectors/autotask/companies/{company_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_company(
        company_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = autotask_client.get_company(company_id)
        return _autotask_response("companies.get", response)

    @app.get("/connectors/itglue/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = itglue_client.health()
        _audit_itglue_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/itglue/organizations")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_organizations(
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = itglue_client.list_organizations(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.itglue_page_size
            ),
        )
        return _itglue_response("organizations.list", response)

    @app.get("/connectors/itglue/organizations/{organization_id}/documents")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_documents(
        organization_id: str,
        request: Request,
        _: ViewerAccess,
        folder_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = itglue_client.list_documents(
            organization_id,
            folder_id=folder_id,
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.itglue_page_size
            ),
        )
        return _itglue_response("documents.list", response)

    @app.get("/connectors/itglue/documents/{document_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_document(
        document_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = itglue_client.get_document(document_id)
        return _itglue_response("documents.get", response)

    @app.get("/connectors/itglue/organizations/{organization_id}/folders")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_folders(
        organization_id: str,
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = itglue_client.list_folders(
            organization_id,
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.itglue_page_size
            ),
        )
        return _itglue_response("folders.list", response)

    @app.get("/connectors/confluence/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def confluence_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = confluence_client.health()
        _audit_confluence_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/confluence/pages")
    @limiter.limit(active_settings.rate_limit_connector)
    def confluence_pages(
        request: Request,
        _: ViewerAccess,
        space_id: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = confluence_client.list_pages(
            space_id=space_id,
            title=title,
            cursor=cursor,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.confluence_page_size
            ),
        )
        return _confluence_response("pages.list", response)

    @app.get("/connectors/confluence/pages/{page_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def confluence_page(page_id: str, request: Request, _: ViewerAccess) -> dict[str, object]:
        response = confluence_client.get_page(page_id)
        return _confluence_response("pages.get", response)

    @app.get("/workflows/templates")
    def workflow_templates(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(template) for template in list_workflow_templates()]

    @app.get("/workflow-templates/gallery")
    def template_gallery(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        return [
            _template_gallery_view(entry)
            for entry in store.list_template_gallery_entries(scoped_client_id)
        ]

    @app.post("/workflow-templates/gallery")
    def create_template_gallery_entry(
        payload: TemplateGalleryCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        template = get_workflow_template(payload.source_template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        try:
            entry = store.create_template_gallery_entry(
                template,
                provenance=payload.provenance,
                client_id=scoped_client_id,
                name=payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(entry)

    @app.get("/workflow-templates/gallery/{entry_id}")
    def template_gallery_detail(entry_id: str, context: ViewerAccess) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        entry = store.get_template_gallery_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        return _template_gallery_view(entry)

    @app.post("/workflow-templates/gallery/{entry_id}/runs")
    def run_template_gallery_entry(
        entry_id: str,
        request: WorkflowRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, request.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        entry = store.get_template_gallery_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        if store.get_ticket(request.ticket_id, client_id=scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        return asdict(
            run_workflow_template(
                store,
                entry.source_template_id,
                request.ticket_id,
                client_id=scoped_client_id,
                actor=context.approver_id or "api",
                trigger_source="template_gallery",
            )
        )

    @app.get("/scheduled-jobs")
    def scheduled_jobs(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        return [_scheduled_job_view(job) for job in scheduler.list_jobs(client_id=scoped_client_id)]

    @app.post("/scheduled-jobs")
    def create_scheduled_job(
        request: ScheduledJobCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        if request.agent_id is not None:
            return _create_scheduled_agent_job(request, context)
        if request.template_id is None:
            raise HTTPException(status_code=422, detail="template_id or agent_id is required")
        if get_workflow_template(request.template_id) is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        ticket_id = _scheduled_ticket_id(request.params)
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = _smart_action_client_scope(context, requested_client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        ticket = store.get_ticket(ticket_id, client_id=scoped_client_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        params = dict(request.params)
        if (requested_client_id is None or not requested_client_id.strip()) and ticket.client_id:
            params["client_id"] = ticket.client_id
        try:
            scheduled_job = scheduler.register(
                request.template_id,
                request.cron,
                params,
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_agent_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if request.template_id is not None:
            raise HTTPException(status_code=422, detail="choose either template_id or agent_id")
        if request.entity_id is None or not request.entity_id.strip():
            raise HTTPException(status_code=422, detail="agent schedules require entity_id")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = _smart_action_client_scope(context, requested_client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        definition = agent_service.get(request.agent_id or "")
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if definition.trigger != "scheduled":
            raise HTTPException(status_code=422, detail="agent is not configured for scheduled execution")
        if definition.client_id is not None and definition.client_id != scoped_client_id:
            raise HTTPException(status_code=404, detail="agent not found")
        effective_client_id = definition.client_id or scoped_client_id
        ticket = store.get_ticket(request.entity_id, client_id=effective_client_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        params = dict(request.params)
        raw_client_id = params.get("client_id")
        if (
            raw_client_id is None
            or (isinstance(raw_client_id, str) and not raw_client_id.strip())
        ) and ticket.client_id:
            params["client_id"] = ticket.client_id
        input_payload = params.get("input", {})
        if not isinstance(input_payload, dict):
            raise HTTPException(status_code=422, detail="params.input must be an object")
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                params,
                job_kind="agent",
                agent_id=definition.id,
                entity_id=request.entity_id,
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    @app.post("/scheduled-jobs/{job_id}/pause")
    def pause_scheduled_job(job_id: int, context: TechnicianAccess) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(scheduler.pause(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @app.post("/scheduled-jobs/{job_id}/resume")
    def resume_scheduled_job(job_id: int, context: TechnicianAccess) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(scheduler.resume(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @app.post("/scheduled-jobs/{job_id}/reschedule")
    def reschedule_scheduled_job(
        job_id: int,
        payload: ScheduledJobRescheduleRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(
                scheduler.reschedule(
                    job_id,
                    cron=payload.cron,
                    schedule_type=payload.schedule_type,
                    interval_seconds=payload.interval_seconds,
                    run_at=payload.run_at,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/scheduled-jobs/{job_id}")
    def delete_scheduled_job(job_id: int, context: TechnicianAccess) -> dict[str, object]:
        try:
            _scheduled_job_for_context(store, job_id, context)
            return _scheduled_job_view(scheduler.remove(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="scheduled job not found") from exc

    @app.post("/workflows/templates/{template_id}/runs")
    def run_workflow(
        template_id: str,
        request: WorkflowRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            return asdict(
                run_workflow_template(
                    store,
                    template_id,
                    request.ticket_id,
                    client_id=request.client_id,
                    actor=context.approver_id or "api",
                    trigger_source="api",
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

    @app.get("/executions")
    def executions(
        context: ViewerAccess,
        kind: str | None = None,
        status: str | None = None,
        started_from: Annotated[str | None, Query(alias="from")] = None,
        started_to: Annotated[str | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        return [
            _execution_run_view(run)
            for run in store.list_execution_runs(
                client_id=scoped_client_id,
                run_kind=kind,
                status=status,
                started_from=started_from,
                started_to=started_to,
            )
        ]

    @app.get("/executions/{execution_id}")
    def execution_detail(
        execution_id: int, context: ViewerAccess, client_id: str | None = None
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="execution not found")
        run = store.get_execution_run(execution_id, client_id=scoped_client_id)
        if run is None or run.id is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return {
            **_execution_run_view(run),
            "steps": [
                _execution_step_view(step) for step in store.list_execution_steps(run.id)
            ],
            "artifacts": [
                _execution_artifact_view(artifact)
                for artifact in store.list_execution_artifacts(run.id)
            ],
        }

    @app.get("/executions/{execution_id}/artifacts/{artifact_id}")
    def execution_artifact_download(
        execution_id: int,
        artifact_id: int,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> FileResponse:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        run = store.get_execution_run(execution_id, client_id=scoped_client_id)
        if run is None or run.id is None:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        artifact = store.get_execution_artifact(artifact_id)
        if artifact is None or artifact.execution_run_id != run.id:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        path = Path(artifact.storage_path).resolve()
        # Artifacts are content-addressed: the file name must be its digest.
        if path.name != artifact.sha256 or not path.is_file():
            raise HTTPException(status_code=404, detail="execution artifact not found")
        return FileResponse(path, media_type=artifact.media_type, filename=artifact.name)

    @app.get("/analytics/summary")
    def analytics_summary(
        context: ViewerAccess,
        started_from: Annotated[str | None, Query(alias="from")] = None,
        started_to: Annotated[str | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        estimates = {
            manifest.action_id: manifest.estimated_minutes_saved
            for manifest in smart_action_service.list()
        }
        if context.role < Role.ADMIN and scoped_client_id is None:
            return _empty_analytics_summary(started_from, started_to)
        return build_analytics_summary(
            store,
            estimates,
            started_from=started_from,
            started_to=started_to,
            client_id=scoped_client_id,
        )

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

    def _audit_hudu_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("hudu.read", read_type, f"{status} count={count}")

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

    def _itglue_response(
        read_type: str,
        response: ItGlueReadResponse,
    ) -> dict[str, object]:
        _audit_itglue_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
        }

    def _audit_itglue_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("itglue.read", read_type, f"{status} count={count}")

    def _confluence_response(
        read_type: str,
        response: ConfluenceReadResponse,
    ) -> dict[str, object]:
        _audit_confluence_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _audit_confluence_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("confluence.read", read_type, f"{status} count={count}")

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
            "job_kind": job.job_kind,
            "template_id": job.template_id,
            "agent_id": job.agent_id,
            "entity_id": job.entity_id,
            "cron": job.cron,
            "schedule_type": job.schedule_type,
            "interval_seconds": job.interval_seconds,
            "run_at": job.run_at,
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


def _agent_definition_view(definition) -> dict[str, object]:
    return cast(
        dict[str, object],
        redact_value(
            {
                "id": definition.id,
                "name": definition.name,
                "description": definition.description,
                "enabled": definition.enabled,
                "trigger": definition.trigger,
                "entity_type": definition.entity_type,
                "filters": definition.filters,
                "enabled_tools": definition.enabled_tools,
                "steps": definition.steps,
                "max_steps": definition.max_steps,
                "execution_timeout_seconds": definition.execution_timeout_seconds,
                "client_id": definition.client_id,
                "version": definition.version,
                "run_once_per_entity": definition.run_once_per_entity,
                "depends_on_agent_ids": definition.depends_on_agent_ids,
                "created_at": definition.created_at,
                "updated_at": definition.updated_at,
            }
        ),
    )


def _event_dispatch_view(result) -> dict[str, object]:
    return {
        "delivery": _event_delivery_view(result.delivery),
        "duplicate": result.duplicate,
        "matched_agent_ids": result.matched_agent_ids,
        "run_ids": result.run_ids,
        "errors": result.errors,
    }


def _event_delivery_view(delivery) -> dict[str, object]:
    return {
        "id": delivery.id,
        "idempotency_key": delivery.idempotency_key,
        "event_type": delivery.event_type,
        "entity_type": delivery.entity_type,
        "entity_id": delivery.entity_id,
        "payload": _safe_redacted_json_object(delivery.payload_json),
        "status": delivery.status,
        "matched_agent_count": delivery.matched_agent_count,
        "agent_ids": _safe_json_values(delivery.agent_ids_json),
        "run_ids": _safe_json_values(delivery.run_ids_json),
        "error_detail": redact_text(delivery.error_detail),
        "received_at": delivery.received_at,
        "processed_at": delivery.processed_at,
        "client_id": delivery.client_id,
    }


def _template_gallery_view(entry) -> dict[str, object]:
    return {
        "id": entry.id,
        "source_template_id": entry.source_template_id,
        "name": entry.name,
        "trigger": entry.trigger,
        "description": entry.description,
        "action_type": entry.action_type,
        "approval_required": entry.approval_required,
        "risk_level": entry.risk_level,
        "preview_fields": _safe_json_values(entry.preview_fields_json),
        "provenance": redact_text(entry.provenance),
        "version": entry.version,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "client_id": entry.client_id,
    }


def _agent_revision_view(revision) -> dict[str, object]:
    return {
        "id": revision.id,
        "agent_id": revision.agent_id,
        "version": revision.version,
        "definition": _safe_redacted_json_object(revision.definition_json),
        "created_at": revision.created_at,
        "client_id": revision.client_id,
    }


def _agent_revision_diff_view(left, right) -> dict[str, object]:
    left_definition = _safe_redacted_json_object(left.definition_json)
    right_definition = _safe_redacted_json_object(right.definition_json)
    changed_fields: list[dict[str, object]] = []
    for field in sorted(set(left_definition) | set(right_definition)):
        before = left_definition.get(field)
        after = right_definition.get(field)
        if before != after:
            changed_fields.append({"field": field, "before": before, "after": after})
    return {
        "agent_id": left.agent_id,
        "from_version": left.version,
        "to_version": right.version,
        "changed": bool(changed_fields),
        "changes": changed_fields,
        "client_id": left.client_id,
    }


def _agent_run_view(run) -> dict[str, object]:
    state = _safe_json_object(run.state_json)
    return cast(
        dict[str, object],
        redact_value(
            {
                "id": run.id,
                "agent_id": run.agent_id,
                "entity_id": run.entity_id,
                "actor": run.actor,
                "status": run.status,
                "current_step": run.current_step,
                "state": state,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "revision_version": run.revision_version,
                "client_id": run.client_id,
            }
        ),
    )


def _agent_backfill_view(backfill) -> dict[str, object]:
    return {
        "id": backfill.id,
        "agent_id": backfill.agent_id,
        "entity_ids": _safe_json_values(backfill.entity_ids_json),
        "input": _safe_redacted_json_object(backfill.input_json),
        "status": backfill.status,
        "next_index": backfill.next_index,
        "processed_count": backfill.processed_count,
        "succeeded_count": backfill.succeeded_count,
        "failed_count": backfill.failed_count,
        "run_ids": _safe_json_values(backfill.run_ids_json),
        "failed_entity_ids": _safe_json_values(backfill.failed_entity_ids_json),
        "actor": redact_text(backfill.actor),
        "error_detail": redact_text(backfill.error_detail),
        "created_at": backfill.created_at,
        "updated_at": backfill.updated_at,
        "client_id": backfill.client_id,
    }


def _execution_run_view(run) -> dict[str, object]:
    return {
        "id": run.id,
        "run_kind": run.run_kind,
        "source_run_id": run.source_run_id,
        "actor": run.actor,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "trigger_source": run.trigger_source,
        "client_id": run.client_id,
    }


def _execution_step_view(step) -> dict[str, object]:
    # Step payloads are redacted at persistence and again here at
    # serialization so legacy rows never surface secrets.
    return {
        "id": step.id,
        "ordinal": step.ordinal,
        "kind": step.kind,
        "name": step.name,
        "status": step.status,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "input_digest": step.input_digest,
        "output_digest": step.output_digest,
        "input": redact_value(_safe_json_value(step.input_json)),
        "output": redact_value(_safe_json_value(step.output_json)),
        "error_detail": redact_text(step.error_detail),
    }


def _execution_artifact_view(artifact) -> dict[str, object]:
    return {
        "id": artifact.id,
        "step_ordinal": artifact.step_ordinal,
        "name": artifact.name,
        "media_type": artifact.media_type,
        "byte_size": artifact.byte_size,
        "sha256": artifact.sha256,
    }


def _safe_json_value(payload_json: str) -> object:
    try:
        return json.loads(payload_json)
    except json.JSONDecodeError:
        return None


def _empty_analytics_summary(
    started_from: str | None, started_to: str | None
) -> dict[str, object]:
    return {
        "range": {"from": started_from, "to": started_to},
        "client_id": None,
        "executions_over_time": [],
        "success_rate": {"total": 0, "succeeded": 0, "rate": 0.0},
        "failures_by_status": [],
        "estimated_minutes_saved": {
            "minutes": 0,
            "estimate": True,
            "derivation": ESTIMATED_MINUTES_SAVED_DERIVATION,
        },
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


def _scheduled_job_for_context(store: Store, job_id: int, context: AuthContext):
    scoped_client_id = _smart_action_client_scope(context, None)
    if context.role < Role.ADMIN and scoped_client_id is None:
        raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
    job = store.get_scheduled_job(job_id)
    if job is None or (
        scoped_client_id is not None and _normalize_client_id(job.client_id) != scoped_client_id
    ):
        raise HTTPException(status_code=404, detail="scheduled job not found")
    return job


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


def _safe_json_values(payload_json: str) -> list[object]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


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
