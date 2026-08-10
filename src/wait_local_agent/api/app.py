from __future__ import annotations

import csv
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
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
from wait_local_agent.communication import ConfiguredCommunicationProvider
from wait_local_agent.config import Settings, load_settings
from wait_local_agent.confluence import ConfluenceClient, ConfluenceReadResponse
from wait_local_agent.connectors import (
    draft_connectwise_ticket_action,
    draft_halopsa_ticket_action,
    draft_m365_authentication_method_delete,
    draft_m365_group_membership,
    draft_m365_license_change,
    draft_m365_mail_message_delete,
    draft_m365_mail_message_move,
    draft_m365_mail_message_read_state,
    draft_m365_mailbox_settings_update,
    draft_m365_managed_device_reboot,
    draft_m365_managed_device_remote_lock,
    draft_m365_managed_device_retirement,
    draft_m365_managed_device_sync,
    draft_m365_password_reset,
    draft_m365_session_revocation,
    draft_m365_user_creation,
    draft_m365_user_disable,
    execute_connectwise_approval_request,
    execute_halopsa_approval_request,
    execute_m365_approval_request,
    list_connector_statuses,
    list_secret_records,
    update_connectwise_approval_fields,
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
from wait_local_agent.m365_graph import (
    M365GraphClient,
    M365GraphGroupReadResponse,
    M365GraphLicenseDetailReadResponse,
    M365GraphLicenseReadResponse,
    M365GraphMailFolderReadResponse,
    M365GraphMailMessageReadResponse,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadResponse,
)
from wait_local_agent.models import (
    AGENT_BACKFILL_MAX_CONCURRENCY,
    DEFAULT_EVENT_MAX_RETRIES,
    DEFAULT_EVENT_RETRY_DELAY_SECONDS,
    MAX_APPROVAL_EXPIRY_SECONDS,
    MAX_EVENT_RETRIES,
    MAX_EVENT_RETRY_DELAY_SECONDS,
    AgentDefinition,
    WorkflowRun,
)
from wait_local_agent.notion import NotionClient, NotionDataSourceResponse, NotionReadResponse
from wait_local_agent.observability import (
    APPROVAL_RATE_DERIVATION,
    ESTIMATED_MINUTES_SAVED_DERIVATION,
    MODEL_COST_DERIVATION,
    TICKET_LIFECYCLE_DERIVATION,
    TICKET_METRICS_DERIVATION,
    build_analytics_summary,
)
from wait_local_agent.providers import probe_model_providers, provider_from_settings
from wait_local_agent.rbac import AuthContext, Role, require_end_user, require_role
from wait_local_agent.reports.builders import (
    build_appliance_hardening_report,
    build_restore_evidence_report,
)
from wait_local_agent.reports.hardening_checks import HardeningContext, run_hardening_checks
from wait_local_agent.reports.models import ReportFormat, ReportType
from wait_local_agent.reports.msp import (
    build_automation_opportunity_report,
    build_qbr_report,
    build_recurring_service_review_report,
)
from wait_local_agent.reports.renderers import redact_text, redact_value, report_as_dict
from wait_local_agent.reports.service import ReportService
from wait_local_agent.scalepad import ScalePadClient, ScalePadClientResponse
from wait_local_agent.scheduler import SchedulerManager, validate_scheduled_report_params
from wait_local_agent.security import auth_required
from wait_local_agent.servicenow import ServiceNowClient, ServiceNowReadResponse
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.sharepoint import SharePointClient, SharePointReadResponse
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store, _normalize_client_id
from wait_local_agent.syncro import SyncroClient, SyncroCommentsResponse, SyncroReadResponse
from wait_local_agent.technician_chat import TechnicianChatParseError, parse_technician_message
from wait_local_agent.timezest import TimeZestClient
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
EndUserAccess = Annotated[AuthContext, Depends(require_end_user)]


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


class ConnectWiseDraftRequest(BaseModel):
    action_type: Literal["update_status", "assign_technician", "update_ticket_fields"]
    fields: dict[str, object]
    client_id: str | None = None


class M365UserDraftRequest(BaseModel):
    user_principal_name: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=256)
    mail_nickname: str = Field(min_length=1, max_length=64)
    temporary_vault_name: str = Field(min_length=14, max_length=128)
    account_enabled: bool = True
    force_change_password_next_sign_in: bool = True
    client_id: str | None = None


class M365UserDisableDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365PasswordResetDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    temporary_vault_name: str = Field(min_length=14, max_length=128)
    force_change_password_next_sign_in: bool = True
    force_change_password_next_sign_in_with_mfa: bool = False
    client_id: str | None = None


class M365AuthenticationMethodDeleteDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    method_type: Literal["fido2", "microsoft_authenticator", "phone", "software_oath"]
    method_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365GroupMembershipDraftRequest(BaseModel):
    group_id: str = Field(min_length=1, max_length=320)
    user_id: str = Field(min_length=1, max_length=320)
    operation: Literal["add", "remove"]
    client_id: str | None = None


class M365LicenseChangeDraftRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=320)
    sku_ids: list[str] = Field(min_length=1, max_length=50)
    operation: Literal["add", "remove"]
    client_id: str | None = None


class M365SessionRevocationDraftRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceRetirementDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceSyncDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceRebootDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceRemoteLockDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365MailboxSettingsUpdateDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    settings: dict[str, str] = Field(min_length=1, max_length=4)
    client_id: str | None = None


class M365MailMessageMoveDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    source_folder_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=320)
    destination_folder_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365MailMessageReadStateDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    source_folder_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=320)
    is_read: bool
    client_id: str | None = None


class M365MailMessageDeleteDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    source_folder_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class WorkflowRunRequest(BaseModel):
    ticket_id: str
    client_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class TemplateGalleryCreateRequest(BaseModel):
    source_template_id: str
    provenance: str = Field(min_length=1, max_length=1000)
    display_name: str | None = Field(default=None, max_length=120)
    instructions: str = Field(default="", max_length=4000)
    client_id: str | None = None


class TemplateGalleryImportRequest(BaseModel):
    format: Literal["wait-local-agent.workflow-template"]
    format_version: Literal[1]
    source_template_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    provenance: str = Field(min_length=1, max_length=1000)
    instructions: str = Field(default="", max_length=4000)
    client_id: str | None = None


class TemplateGalleryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    instructions: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None
    client_id: str | None = None


class TemplateGalleryRestoreRequest(BaseModel):
    client_id: str | None = None


class SmartActionInvokeRequest(BaseModel):
    payload: dict[str, object] = Field(default_factory=dict)
    confirm: bool = False
    client_id: str | None = None


class TechnicianChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    ticket_id: str | None = Field(default=None, max_length=100)
    client_id: str | None = None


class TechnicianChatSessionCreateRequest(BaseModel):
    ticket_id: str | None = Field(default=None, max_length=100)
    client_id: str | None = None


class TechnicianChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    ticket_id: str | None = Field(default=None, max_length=100)


class EndUserTicketCreateRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)


class EndUserBrandingResponse(BaseModel):
    brand_name: str
    brand_tagline: str
    brand_logo_data_uri: str
    brand_accent_color: str
    brand_surface_color: str


class EndUserMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class EndUserHaloSyncDraftRequest(BaseModel):
    external_ticket_id: str = Field(min_length=1, max_length=100)


class ClientReportRequest(BaseModel):
    period_start: date
    period_end: date
    client_id: str | None = Field(default=None, min_length=1, max_length=200)


class AgentStepRequest(BaseModel):
    tool_id: str
    payload: dict[str, object] = Field(default_factory=dict)


class AgentApprovalRuleRequest(BaseModel):
    tool_id: str = Field(min_length=1, max_length=120)
    when: dict[str, list[str]] = Field(min_length=1, max_length=3)


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
    execution_window_start: str | None = Field(default=None, max_length=5)
    execution_window_end: str | None = Field(default=None, max_length=5)
    execution_window_timezone: str = Field(default="UTC", min_length=1, max_length=100)
    context_sources: list[Literal["ticket", "client", "knowledge"]] = Field(
        default_factory=list, max_length=3
    )
    approval_expiry_seconds: int | None = Field(
        default=None, ge=1, le=MAX_APPROVAL_EXPIRY_SECONDS
    )
    result_aware: bool = False
    approval_required_tools: list[str] = Field(default_factory=list, max_length=8)
    approval_rules: list[AgentApprovalRuleRequest] = Field(default_factory=list, max_length=8)


class AgentRunStartRequest(BaseModel):
    entity_id: str
    input: dict[str, object] = Field(default_factory=dict)
    client_id: str | None = None


class AgentPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2_000)
    entity_id: str = Field(min_length=1, max_length=100)
    max_steps: int = Field(default=8, ge=1, le=8)
    client_id: str | None = None


class AgentBackfillCreateRequest(BaseModel):
    agent_id: str
    entity_ids: list[str] = Field(min_length=1, max_length=100)
    input: dict[str, object] = Field(default_factory=dict)
    max_concurrency: int = Field(default=1, ge=1, le=AGENT_BACKFILL_MAX_CONCURRENCY)
    client_id: str | None = None


class AgentBackfillPreviewRequest(BaseModel):
    agent_id: str
    entity_ids: list[str] = Field(min_length=1, max_length=100)
    input: dict[str, object] = Field(default_factory=dict)
    max_concurrency: int = Field(default=1, ge=1, le=AGENT_BACKFILL_MAX_CONCURRENCY)
    client_id: str | None = None


class EventIngestRequest(BaseModel):
    event_type: str
    entity_type: Literal["ticket"] = "ticket"
    entity_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = None
    client_id: str | None = None
    max_retries: int = Field(default=DEFAULT_EVENT_MAX_RETRIES, ge=0, le=MAX_EVENT_RETRIES)
    retry_delay_seconds: int = Field(
        default=DEFAULT_EVENT_RETRY_DELAY_SECONDS,
        ge=1,
        le=MAX_EVENT_RETRY_DELAY_SECONDS,
    )


class ScheduledJobCreateRequest(BaseModel):
    template_id: str | None = None
    report_type: Literal["qbr", "automation_opportunity", "recurring_service_review"] | None = None
    agent_id: str | None = None
    entity_id: str | None = None
    cron: str = ""
    schedule_type: Literal["cron", "interval", "once"] = "cron"
    interval_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    run_at: str | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    params: dict[str, object] = Field(default_factory=dict)


class ScheduledJobRescheduleRequest(BaseModel):
    cron: str = ""
    schedule_type: Literal["cron", "interval", "once"] = "cron"
    interval_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    run_at: str | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)


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
    notion_client = NotionClient(active_settings)
    sharepoint_client = SharePointClient(active_settings)
    timezest_client = TimeZestClient(active_settings)
    scalepad_client = ScalePadClient(active_settings)
    m365_client = M365GraphClient(active_settings)
    update_status_cache = UpdateStatusCache(ttl_seconds=3600.0)
    report_service = ReportService(store)
    collector_service = CollectorService(store, default_registry)
    smart_action_service = SmartActionService(
        store,
        active_settings,
        collector_service=collector_service,
        halopsa_client=halopsa_client,
        hudu_client=hudu_client,
        connectwise_client=connectwise_client,
        syncro_client=syncro_client,
        servicenow_client=servicenow_client,
        autotask_client=autotask_client,
        itglue_client=itglue_client,
        confluence_client=confluence_client,
        notion_client=notion_client,
        sharepoint_client=sharepoint_client,
        timezest_client=timezest_client,
        scalepad_client=scalepad_client,
        m365_client=m365_client,
        communication_provider=ConfiguredCommunicationProvider(active_settings),
    )
    agent_service = AgentService(store, active_settings, smart_action_service)
    event_dispatcher = EventDispatcher(store, agent_service)
    scheduler = SchedulerManager(
        store,
        enabled=active_settings.scheduler_enabled,
        agent_service=agent_service,
        smart_action_service=smart_action_service,
        event_dispatcher=event_dispatcher,
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
            "offline_mode": active_settings.offline_mode,
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
            "sharepoint_configured": bool(
                active_settings.sharepoint_base_url
                and active_settings.sharepoint_access_token
            ),
            "m365_configured": bool(
                active_settings.m365_graph_base_url
                and active_settings.m365_access_token
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
            "cloud_fallback_enabled": active_settings.allow_cloud_fallback,
            "offline_mode": active_settings.offline_mode,
            "remote_model_provider": active_settings.remote_model_provider,
            "remote_model_configured": bool(
                active_settings.remote_model_provider
                and active_settings.remote_model_base_url
                and active_settings.remote_model_name
                and active_settings.remote_model_api_key
            ),
            "remote_model_enabled": bool(
                active_settings.allow_llm_inference
                and active_settings.allow_cloud_fallback
                and not active_settings.offline_mode
                and active_settings.remote_model_provider
                and active_settings.remote_model_base_url
                and active_settings.remote_model_name
                and active_settings.remote_model_api_key
            ),
            "model_input_cost_usd_per_million_tokens": active_settings.model_input_cost_usd_per_million_tokens,
            "model_output_cost_usd_per_million_tokens": active_settings.model_output_cost_usd_per_million_tokens,
            "vector_backend": active_settings.vector_backend,
            "document_parser": active_settings.document_parser,
            "ocr_enabled": active_settings.allow_ocr,
            "embedding_provider": active_settings.embedding_provider,
            "embedding_model": active_settings.embedding_model,
            "qdrant_collection": active_settings.qdrant_collection,
        }

    @app.get("/settings/providers/health")
    def provider_health(_: AdminAccess) -> dict[str, object]:
        result = probe_model_providers(active_settings)
        for name, status in result.items():
            if isinstance(status, dict):
                store.add_audit_event(
                    "model_provider.health",
                    str(name),
                    str(status.get("status", "unknown")),
                )
        return result

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

    @app.post("/agents/plan")
    def plan_agent(payload: AgentPlanRequest, context: TechnicianAccess) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            plan = agent_service.plan(
                payload.instruction,
                entity_id=payload.entity_id,
                client_id=scoped_client_id,
                max_steps=payload.max_steps,
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(plan)

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
                execution_window_start=payload.execution_window_start,
                execution_window_end=payload.execution_window_end,
                execution_window_timezone=payload.execution_window_timezone,
                context_sources=list(payload.context_sources),
                approval_expiry_seconds=payload.approval_expiry_seconds,
                result_aware=payload.result_aware,
                approval_required_tools=payload.approval_required_tools,
                approval_rules=[rule.model_dump() for rule in payload.approval_rules],
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
                execution_window_start=payload.execution_window_start,
                execution_window_end=payload.execution_window_end,
                execution_window_timezone=payload.execution_window_timezone,
                context_sources=list(payload.context_sources),
                approval_expiry_seconds=payload.approval_expiry_seconds,
                result_aware=payload.result_aware,
                approval_required_tools=payload.approval_required_tools,
                approval_rules=[rule.model_dump() for rule in payload.approval_rules],
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
                execution_window_start=payload.execution_window_start,
                execution_window_end=payload.execution_window_end,
                execution_window_timezone=payload.execution_window_timezone,
                context_sources=list(payload.context_sources),
                approval_expiry_seconds=payload.approval_expiry_seconds,
                result_aware=payload.result_aware,
                approval_required_tools=payload.approval_required_tools,
                approval_rules=[rule.model_dump() for rule in payload.approval_rules],
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
                actor_role=context.role,
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
        def run_entity(entity_id: str):
            try:
                result = agent_service.run(
                    definition,
                    entity_id=entity_id,
                    actor=backfill.actor or context.approver_id or "api",
                    input_payload=input_payload,
                    actor_role=context.role,
                )
                if result.status in {"completed", "pending_approval"}:
                    return result, None
                return result, f"{entity_id}: agent run status {result.status}"
            except Exception as exc:  # noqa: BLE001 - continue independent entities
                return None, redact_text(f"{entity_id}: {exc}")

        max_concurrency = min(
            max(1, backfill.max_concurrency), AGENT_BACKFILL_MAX_CONCURRENCY
        )
        for batch_start in range(backfill.next_index, len(entity_ids), max_concurrency):
            batch = entity_ids[batch_start : batch_start + max_concurrency]
            if max_concurrency == 1:
                outcomes = [run_entity(batch[0])]
            else:
                with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
                    outcomes = list(executor.map(run_entity, batch))
            for offset, (result, error_detail) in enumerate(outcomes):
                index = batch_start + offset
                entity_id = entity_ids[index]
                if result is not None:
                    if result.run_id:
                        run_ids.append(result.run_id)
                    if error_detail is None:
                        succeeded_count += 1
                    else:
                        failed_count += 1
                        failed_entity_ids.append(entity_id)
                        errors.append(error_detail)
                else:
                    failed_count += 1
                    failed_entity_ids.append(entity_id)
                    errors.append(error_detail or f"{entity_id}: agent run failed")
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
            max_concurrency=payload.max_concurrency,
            client_id=scoped_client_id,
        )
        return _agent_backfill_view(backfill)

    @app.post("/agent-backfills/preview")
    def preview_agent_backfill(
        payload: AgentBackfillPreviewRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _backfill_scope(context, payload.client_id)
        if len(set(payload.entity_ids)) != len(payload.entity_ids):
            raise HTTPException(status_code=422, detail="entity_ids must not contain duplicates")
        definition = agent_service.get(payload.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        missing_entity_ids = [
            entity_id
            for entity_id in payload.entity_ids
            if store.get_ticket(entity_id, client_id=scoped_client_id) is None
        ]
        if missing_entity_ids:
            raise HTTPException(
                status_code=404,
                detail=f"ticket not found: {missing_entity_ids[0]}",
            )
        execution_mode = "sequential" if payload.max_concurrency == 1 else "bounded_parallel"
        return {
            "dry_run": True,
            "agent_id": payload.agent_id,
            "entity_count": len(payload.entity_ids),
            "estimated_runs": len(payload.entity_ids),
            "max_concurrency": payload.max_concurrency,
            "execution_mode": execution_mode,
            "will_persist": False,
            "input": _redact_payload(payload.input),
            "client_id": scoped_client_id,
        }

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
                actor_role=context.role,
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
                max_retries=payload.max_retries,
                retry_delay_seconds=payload.retry_delay_seconds,
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

    @app.post("/automation/event-deliveries/{delivery_id}/retry")
    @limiter.limit(active_settings.rate_limit_general)
    def retry_event_delivery(
        request: Request,
        delivery_id: int,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="event delivery not found")
        try:
            result = event_dispatcher.retry(
                delivery_id,
                client_id=scoped_client_id,
                actor=context.approver_id or "operator",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="event delivery not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _event_dispatch_view(result)

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
            manifest = smart_action_service.describe(action_id)
            if manifest.required_role.strip().lower() == "admin" and context.role < Role.ADMIN:
                raise HTTPException(status_code=403, detail="smart action requires admin authority")
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

    @app.post("/technician/chat")
    @limiter.limit(active_settings.rate_limit_connector)
    def technician_chat(
        payload: TechnicianChatRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return _invoke_technician_chat_message(
                store,
                smart_action_service,
                agent_service,
                payload.message,
                ticket_id=payload.ticket_id,
                actor=context.approver_id or "api",
                client_id=scoped_client_id,
            )
        except TechnicianChatParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="requested technician action is unavailable") from exc

    @app.post("/technician/chat/sessions")
    @limiter.limit(active_settings.rate_limit_connector)
    def create_technician_chat_session(
        payload: TechnicianChatSessionCreateRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="chat sessions require a client scope")
        if payload.ticket_id and store.get_ticket(payload.ticket_id, scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found in client scope")
        try:
            session = store.create_technician_chat_session(
                client_id=scoped_client_id,
                principal_id=context.approver_id or "api",
                ticket_id=payload.ticket_id,
            )
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _technician_chat_session_view(store, session)

    @app.get("/technician/chat/sessions")
    @limiter.limit(active_settings.rate_limit_connector)
    def list_technician_chat_sessions(
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        sessions = store.list_technician_chat_sessions(
            client_id=scoped_client_id,
            principal_id=principal_id,
        )
        return [_technician_chat_session_view(store, session) for session in sessions]

    @app.get("/technician/chat/sessions/{session_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def get_technician_chat_session(
        session_id: str,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        session = store.get_technician_chat_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="technician chat session not found")
        return _technician_chat_session_view(store, session)

    @app.post("/technician/chat/sessions/{session_id}/messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def send_technician_chat_message(
        session_id: str,
        payload: TechnicianChatMessageRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        session = store.get_technician_chat_session(
            session_id,
            client_id=scoped_client_id,
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
            )
        except TechnicianChatParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="requested technician action is unavailable") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found in client scope") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/technician/chat/sessions/{session_id}/close")
    @limiter.limit(active_settings.rate_limit_connector)
    def close_technician_chat_session(
        session_id: str,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = None if context.role >= Role.ADMIN else context.approver_id or "api"
        session = store.close_technician_chat_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="technician chat session not found")
        return _technician_chat_session_view(store, session)

    @app.get("/end-user/config", response_model=EndUserBrandingResponse)
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_config(
        request: Request,
        context: EndUserAccess,
    ) -> EndUserBrandingResponse:
        if not context.client_id or not context.principal_id:
            raise HTTPException(status_code=403, detail="end-user identity is not fully scoped")
        return EndUserBrandingResponse(
            brand_name=_end_user_branding_text(active_settings.end_user_brand_name, "WAIT Support"),
            brand_tagline=_end_user_branding_text(
                active_settings.end_user_brand_tagline, "Private help desk"
            ),
            brand_logo_data_uri=_end_user_brand_logo_data_uri(
                active_settings.end_user_brand_logo_data_uri
            ),
            brand_accent_color=_end_user_brand_color(
                active_settings.end_user_brand_accent_color, "#1f6f55"
            ),
            brand_surface_color=_end_user_brand_color(
                active_settings.end_user_brand_surface_color, "#f3f5f2"
            ),
        )

    @app.post("/end-user/tickets")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_create_ticket(
        payload: EndUserTicketCreateRequest,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        if not context.client_id or not context.principal_id:
            raise HTTPException(status_code=403, detail="end-user identity is not fully scoped")
        ticket = store.create_end_user_ticket(
            client_id=context.client_id,
            requester_id=context.principal_id,
            subject=payload.subject,
            body=payload.body,
        )
        return _end_user_ticket_view(ticket)

    @app.get("/end-user/tickets/{ticket_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_ticket_status(
        ticket_id: str,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        if not context.client_id or not context.principal_id or not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        ticket = store.get_end_user_ticket(
            ticket_id,
            client_id=context.client_id,
            requester_id=context.principal_id,
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _end_user_ticket_view(ticket)

    @app.get("/end-user/tickets/{ticket_id}/messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_ticket_messages(
        ticket_id: str,
        request: Request,
        context: EndUserAccess,
    ) -> list[dict[str, object]]:
        if not context.client_id or not context.principal_id or not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        ticket = store.get_end_user_ticket(
            ticket_id,
            client_id=context.client_id,
            requester_id=context.principal_id,
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return [
            _end_user_message_view(message)
            for message in store.list_end_user_messages(
                ticket_id,
                client_id=context.client_id,
                requester_id=context.principal_id,
            )
        ]

    @app.post("/end-user/tickets/{ticket_id}/messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_add_ticket_message(
        ticket_id: str,
        payload: EndUserMessageRequest,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        if not context.client_id or not context.principal_id:
            raise HTTPException(status_code=403, detail="end-user identity is not fully scoped")
        if not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        message = store.create_end_user_message(
            ticket_id,
            client_id=context.client_id,
            requester_id=context.principal_id,
            body=payload.body,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _end_user_message_view(message)

    @app.get("/tickets/{ticket_id}/end-user-messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def ticket_end_user_messages(
        ticket_id: str,
        request: Request,
        context: ViewerAccess,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if scoped_client_id is None and context.role >= Role.ADMIN:
            ticket = store.get_ticket(ticket_id)
            scoped_client_id = ticket.client_id if ticket is not None else None
        if scoped_client_id is None:
            return []
        return [
            _operator_end_user_message_view(message)
            for message in store.list_end_user_messages_for_operator(
                ticket_id, client_id=scoped_client_id
            )
        ]

    @app.post("/tickets/{ticket_id}/end-user-messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def add_ticket_end_user_message(
        ticket_id: str,
        payload: EndUserMessageRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if scoped_client_id is None and context.role >= Role.ADMIN:
            ticket = store.get_ticket(ticket_id)
            scoped_client_id = ticket.client_id if ticket is not None else None
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="technician has no tenant scope")
        message = store.create_support_end_user_message(
            ticket_id,
            client_id=scoped_client_id,
            author_id=context.approver_id or "local-technician",
            body=payload.body,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _operator_end_user_message_view(message)

    @app.post("/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def draft_end_user_halopsa_sync(
        ticket_id: str,
        message_id: int,
        payload: EndUserHaloSyncDraftRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(
            context,
            active_settings.client_id if context.role >= Role.ADMIN else None,
        )
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="technician has no tenant scope")
        local_ticket = store.get_ticket(ticket_id, client_id=scoped_client_id)
        if local_ticket is None or not local_ticket.requester_id:
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
        external_ticket_id = payload.external_ticket_id.strip()
        if not _safe_external_ticket_id(external_ticket_id):
            raise HTTPException(status_code=422, detail="external HaloPSA ticket id is invalid")
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

    @app.post("/end-user/tickets/{ticket_id}/escalate")
    @limiter.limit(active_settings.rate_limit_connector)
    def end_user_escalate_ticket(
        ticket_id: str,
        request: Request,
        context: EndUserAccess,
    ) -> dict[str, object]:
        if not context.client_id or not context.principal_id:
            raise HTTPException(status_code=403, detail="end-user identity is not fully scoped")
        if not _safe_end_user_ticket_id(ticket_id):
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        ticket = store.escalate_end_user_ticket(
            ticket_id,
            client_id=context.client_id,
            requester_id=context.principal_id,
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="end-user ticket not found")
        return _end_user_ticket_view(ticket)

    @app.get("/tickets/{ticket_id}/summary")
    def summarize_ticket(ticket_id: str, _: ViewerAccess) -> dict[str, object]:
        try:
            return asdict(service.summarize(ticket_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc

    @app.get("/tickets/{ticket_id}/notes")
    def ticket_notes(ticket_id: str, context: ViewerAccess) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if scoped_client_id is None and context.role >= Role.ADMIN:
            ticket = store.get_ticket(ticket_id)
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

    @app.get("/tickets/{ticket_id}/status-history")
    def ticket_status_history(ticket_id: str, context: ViewerAccess) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if scoped_client_id is None and context.role >= Role.ADMIN:
            ticket = store.get_ticket(ticket_id)
            scoped_client_id = ticket.client_id if ticket is not None else None
        if scoped_client_id is None:
            return []
        return store.list_ticket_status_history(ticket_id, client_id=scoped_client_id)

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
            if approval.action_type.startswith("connectwise."):
                approval = update_connectwise_approval_fields(
                    store, request_id, request.fields, request.comment
                )
            else:
                approval = update_halopsa_approval_fields(
                    store, request_id, request.fields, request.comment
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
            if existing_approval.action_type.startswith("m365.") and context.role < Role.ADMIN:
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
                    approval = execute_connectwise_approval_request(
                        store, connectwise_client, request_id
                    )
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

    @app.post("/reports/qbr")
    def create_qbr_report(
        request: ClientReportRequest,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scoped_client_id = _report_client_scope(context, request.client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        estimates = {
            manifest.action_id: manifest.estimated_minutes_saved
            for manifest in smart_action_service.list()
        }
        sections, metadata = build_qbr_report(
            store,
            estimates,
            client_id=scoped_client_id,
            period_start=request.period_start.isoformat(),
            period_end=request.period_end.isoformat(),
        )
        report = report_service.create_report(
            ReportType.QBR,
            f"Quarterly business review — {scoped_client_id}",
            sections,
            created_by=context.approver_id or "system",
            client_id=scoped_client_id,
            metadata=metadata,
        )
        return report_as_dict(report)

    @app.post("/reports/automation-opportunity")
    def create_automation_opportunity_report(
        request: ClientReportRequest,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scoped_client_id = _report_client_scope(context, request.client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        estimates = {
            manifest.action_id: manifest.estimated_minutes_saved
            for manifest in smart_action_service.list()
        }
        sections, metadata = build_automation_opportunity_report(
            store,
            estimates,
            client_id=scoped_client_id,
            period_start=request.period_start.isoformat(),
            period_end=request.period_end.isoformat(),
        )
        report = report_service.create_report(
            ReportType.AUTOMATION_OPPORTUNITY,
            f"Automation opportunities — {scoped_client_id}",
            sections,
            created_by=context.approver_id or "system",
            client_id=scoped_client_id,
            metadata=metadata,
        )
        return report_as_dict(report)

    @app.post("/reports/recurring-service-review")
    def create_recurring_service_review_report(
        request: ClientReportRequest,
        context: ViewerAccess,
        follow_up_after_days: int = Query(default=14, ge=1, le=90),
    ) -> dict[str, object]:
        scoped_client_id = _report_client_scope(context, request.client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        try:
            sections, metadata = build_recurring_service_review_report(
                store,
                client_id=scoped_client_id,
                period_start=request.period_start.isoformat(),
                period_end=request.period_end.isoformat(),
                follow_up_after_days=follow_up_after_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        report = report_service.create_report(
            ReportType.RECURRING_SERVICE_REVIEW,
            f"Recurring service review — {scoped_client_id}",
            sections,
            created_by=context.approver_id or "system",
            client_id=scoped_client_id,
            metadata=metadata,
        )
        return report_as_dict(report)

    @app.get("/reports")
    def reports(
        context: ViewerAccess,
        report_type: ReportType | None = None,
        client_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, object]]:
        scoped_client_id = _report_client_scope(context, client_id or None)
        stored = report_service.list_reports(
            report_type=report_type,
            client_id=scoped_client_id or "",
            project_id=project_id,
        )
        return [report_as_dict(report) for report in stored]

    @app.get("/reports/{report_id}")
    def report_detail(report_id: str, context: ViewerAccess) -> dict[str, object]:
        report = report_service.get_report(report_id, client_id=_report_client_scope(context, None))
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return report_as_dict(report)

    @app.get("/reports/{report_id}/export")
    def report_export(
        report_id: str,
        context: ViewerAccess,
        export_format: Literal["json", "markdown", "pdf"] = "json",
    ) -> Response:
        try:
            rendered = report_service.export_report(
                report_id,
                ReportFormat(export_format),
                client_id=_report_client_scope(context, None),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="report not found") from exc
        media_type = {"json": "application/json", "markdown": "text/markdown", "pdf": "application/pdf"}[export_format]
        extension = {"json": "json", "markdown": "md", "pdf": "pdf"}[export_format]
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

    @app.post("/connectors/connectwise/tickets/{ticket_id}/drafts")
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
                client_id=_approval_client_scope(context, payload.client_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _connectwise_draft_view(draft)

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

    @app.get("/connectors/connectwise/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def connectwise_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = connectwise_client.write_health()
        store.add_audit_event("connectwise.write_health", "connectwise", result.status)
        return asdict(result)

    @app.post("/connectors/connectwise/approval-requests/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_connectwise_approval(
        request_id: int,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_in_scope(context, approval):
                raise KeyError(request_id)
            return _approval_view(execute_connectwise_approval_request(store, connectwise_client, request_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.get("/connectors/syncro/tickets/{ticket_id}/comments")
    @limiter.limit(active_settings.rate_limit_connector)
    def syncro_ticket_comments(
        ticket_id: str,
        request: Request,
        _: ViewerAccess,
        page: int = 1,
        per_page: int = 10,
    ) -> dict[str, object]:
        response = syncro_client.list_ticket_comments(
            ticket_id,
            page=page,
            per_page=per_page,
        )
        return _syncro_comments_response("tickets.comments", response)

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

    @app.get("/connectors/servicenow/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def servicenow_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = servicenow_client.write_health()
        store.add_audit_event("servicenow.write_health", "servicenow", result.status)
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

    @app.get("/connectors/autotask/write-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def autotask_write_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = autotask_client.write_health()
        store.add_audit_event("autotask.write_health", "autotask", result.status)
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

    @app.get("/connectors/notion/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = notion_client.health()
        _audit_notion_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/notion/pages")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_pages(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        query: str = "",
        page_size: int | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="Notion reads require a tenant scope")
        response = notion_client.search_pages(
            client_id=scoped_client_id,
            query=query,
            page_size=page_size if page_size is not None else active_settings.notion_page_size,
        )
        return _notion_response("pages.search", response)

    @app.get("/connectors/notion/pages/{page_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_page(
        page_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="Notion reads require a tenant scope")
        response = notion_client.get_page(page_id, client_id=scoped_client_id)
        return _notion_response("pages.get", response)

    @app.get("/connectors/notion/data-sources/{data_source_id}/pages")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_data_source_pages(
        data_source_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        start_cursor: str = "",
        page_size: int | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if scoped_client_id is None:
            raise HTTPException(
                status_code=403, detail="Notion data-source reads require a tenant scope"
            )
        response = notion_client.query_data_source(
            data_source_id,
            client_id=scoped_client_id,
            page_size=page_size if page_size is not None else active_settings.notion_page_size,
            start_cursor=start_cursor,
        )
        return _notion_response("data-sources.query", response)

    @app.get("/connectors/notion/data-sources/{data_source_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_data_source(
        data_source_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if scoped_client_id is None:
            raise HTTPException(
                status_code=403, detail="Notion data-source reads require a tenant scope"
            )
        response = notion_client.get_data_source(data_source_id, client_id=scoped_client_id)
        return _notion_data_source_response("data-sources.get", response)

    @app.get("/connectors/sharepoint/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = sharepoint_client.health()
        _audit_sharepoint_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/sharepoint/sites")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_sites(
        request: Request,
        _: ViewerAccess,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = sharepoint_client.list_sites(
            cursor=cursor,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.sharepoint_page_size
            ),
        )
        return _sharepoint_response("sites.list", response)

    @app.get("/connectors/sharepoint/sites/{site_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_site(site_id: str, request: Request, _: ViewerAccess) -> dict[str, object]:
        response = sharepoint_client.get_site(site_id)
        return _sharepoint_response("sites.get", response)

    @app.get("/connectors/sharepoint/sites/{site_id}/documents")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_documents(
        site_id: str,
        request: Request,
        _: ViewerAccess,
        parent_item_id: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = sharepoint_client.list_documents(
            site_id,
            parent_item_id=parent_item_id,
            cursor=cursor,
            page_size=(
                page_size
                if page_size is not None
                else active_settings.sharepoint_page_size
            ),
        )
        return _sharepoint_response("documents.list", response)

    @app.get("/connectors/sharepoint/sites/{site_id}/documents/{item_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_document(
        site_id: str,
        item_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = sharepoint_client.get_document(site_id, item_id)
        return _sharepoint_response("documents.get", response)

    @app.get("/connectors/sharepoint/sites/{site_id}/documents/{item_id}/content")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_document_content(
        site_id: str,
        item_id: str,
        request: Request,
        _: ViewerAccess,
    ) -> dict[str, object]:
        response = sharepoint_client.get_document_content(site_id, item_id)
        return _sharepoint_response("documents.content", response)

    @app.get("/connectors/scalepad/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = scalepad_client.health()
        _audit_scalepad_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/scalepad/clients")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_client_lookup(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="ScalePad reads require a tenant scope")
        response = scalepad_client.get_client(client_id=scoped_client_id)
        return _scalepad_response("clients.get", response)

    @app.get("/connectors/m365/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = m365_client.health()
        _audit_m365_read("health", result.status, result.count)
        return asdict(result)

    @app.get("/connectors/m365/users")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_users(
        request: Request,
        _: ViewerAccess,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = m365_client.list_users(
            identity=identity,
            cursor=cursor,
            page_size=(
                page_size if page_size is not None else active_settings.m365_page_size
            ),
        )
        return _m365_response("users.list", response)

    @app.get("/connectors/m365/groups")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_groups(
        request: Request,
        _: ViewerAccess,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = m365_client.list_groups(
            identity=identity,
            cursor=cursor,
            page_size=(
                page_size if page_size is not None else active_settings.m365_page_size
            ),
        )
        return _m365_group_response("groups.list", response)

    @app.get("/connectors/m365/licenses")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_licenses(
        request: Request,
        _: ViewerAccess,
        cursor: str | None = None,
    ) -> dict[str, object]:
        response = m365_client.list_subscribed_skus(cursor=cursor)
        return _m365_license_response("licenses.list", response)

    @app.get("/connectors/m365/users/license-details")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_user_license_details(
        request: Request,
        _: ViewerAccess,
        identity: str,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = m365_client.list_license_details(
            identity=identity,
            cursor=cursor,
            page_size=(
                page_size if page_size is not None else active_settings.m365_page_size
            ),
        )
        return _m365_license_detail_response("users.license-details.list", response)

    @app.get("/connectors/m365/mail-folders")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_folders(
        request: Request,
        _: ViewerAccess,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = m365_client.list_mail_folders(
            identity=identity,
            cursor=cursor,
            page_size=(
                page_size if page_size is not None else active_settings.m365_page_size
            ),
        )
        return _m365_mail_folder_response("mail-folders.list", response)

    @app.get("/connectors/m365/mail-messages")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_messages(
        request: Request,
        _: ViewerAccess,
        identity: str | None = None,
        folder_id: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = m365_client.list_mail_messages(
            identity=identity,
            folder_id=folder_id,
            cursor=cursor,
            page_size=(
                page_size if page_size is not None else active_settings.m365_page_size
            ),
        )
        return _m365_mail_message_response("mail-messages.list", response)

    @app.get("/connectors/m365/managed-devices")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_devices(
        request: Request,
        _: ViewerAccess,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, object]:
        response = m365_client.list_managed_devices(
            cursor=cursor,
            page_size=(
                page_size if page_size is not None else active_settings.m365_page_size
            ),
        )
        return _m365_managed_device_response("managed-devices.list", response)

    @app.post("/connectors/m365/users/drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_user_draft(
        payload: M365UserDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_user_creation(
                store,
                user_principal_name=payload.user_principal_name,
                display_name=payload.display_name,
                mail_nickname=payload.mail_nickname,
                temporary_vault_name=payload.temporary_vault_name,
                account_enabled=payload.account_enabled,
                force_change_password_next_sign_in=payload.force_change_password_next_sign_in,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/users/disable-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_user_disable_draft(
        payload: M365UserDisableDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_user_disable(
                store,
                user_identity=payload.user_identity,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/users/password-reset-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_password_reset_draft(
        payload: M365PasswordResetDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_password_reset(
                store,
                user_identity=payload.user_identity,
                temporary_vault_name=payload.temporary_vault_name,
                force_change_password_next_sign_in=payload.force_change_password_next_sign_in,
                force_change_password_next_sign_in_with_mfa=payload.force_change_password_next_sign_in_with_mfa,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/users/authentication-method-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_authentication_method_delete_draft(
        payload: M365AuthenticationMethodDeleteDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_authentication_method_delete(
                store,
                user_identity=payload.user_identity,
                method_type=payload.method_type,
                method_id=payload.method_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/groups/membership-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_group_membership_draft(
        payload: M365GroupMembershipDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_group_membership(
                store,
                group_id=payload.group_id,
                user_id=payload.user_id,
                operation=payload.operation,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/users/license-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_license_change_draft(
        payload: M365LicenseChangeDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_license_change(
                store,
                user_id=payload.user_id,
                sku_ids=payload.sku_ids,
                operation=payload.operation,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/users/session-revocation-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_session_revocation_draft(
        payload: M365SessionRevocationDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_session_revocation(
                store,
                user_id=payload.user_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/managed-devices/retire-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_retirement_draft(
        payload: M365ManagedDeviceRetirementDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_managed_device_retirement(
                store,
                device_id=payload.device_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/managed-devices/sync-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_sync_draft(
        payload: M365ManagedDeviceSyncDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_managed_device_sync(
                store,
                device_id=payload.device_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/managed-devices/reboot-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_reboot_draft(
        payload: M365ManagedDeviceRebootDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_managed_device_reboot(
                store,
                device_id=payload.device_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/managed-devices/remote-lock-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_managed_device_remote_lock_draft(
        payload: M365ManagedDeviceRemoteLockDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_managed_device_remote_lock(
                store,
                device_id=payload.device_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/users/mailbox-settings-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mailbox_settings_update_draft(
        payload: M365MailboxSettingsUpdateDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_mailbox_settings_update(
                store,
                user_identity=payload.user_identity,
                settings=payload.settings,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/mail-messages/move-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_message_move_draft(
        payload: M365MailMessageMoveDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_mail_message_move(
                store,
                user_identity=payload.user_identity,
                source_folder_id=payload.source_folder_id,
                message_id=payload.message_id,
                destination_folder_id=payload.destination_folder_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/mail-messages/read-state-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_message_read_state_draft(
        payload: M365MailMessageReadStateDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_mail_message_read_state(
                store,
                user_identity=payload.user_identity,
                source_folder_id=payload.source_folder_id,
                message_id=payload.message_id,
                is_read=payload.is_read,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/mail-messages/delete-drafts")
    @limiter.limit(active_settings.rate_limit_connector)
    def m365_mail_message_delete_draft(
        payload: M365MailMessageDeleteDraftRequest,
        request: Request,
        _: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = draft_m365_mail_message_delete(
                store,
                user_identity=payload.user_identity,
                source_folder_id=payload.source_folder_id,
                message_id=payload.message_id,
                client_id=payload.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _approval_view(approval)

    @app.post("/connectors/m365/approval-requests/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_m365_user_creation(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        try:
            approval = store.get_approval_request(request_id)
            if approval is None or not _approval_in_scope(context, approval):
                raise KeyError(request_id)
            return _approval_view(
                execute_m365_approval_request(
                    store,
                    m365_client,
                    SecretVault(active_settings.vault_path),
                    request_id,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval request not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
                instructions=payload.instructions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(entry)

    @app.get("/workflow-templates/gallery/{entry_id}/export")
    def export_template_gallery_entry(entry_id: str, context: ViewerAccess) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        entry = store.get_template_gallery_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        return _template_gallery_export_view(entry)

    @app.post("/workflow-templates/gallery/import")
    def import_template_gallery_entry(
        payload: TemplateGalleryImportRequest,
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
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                enabled=False,
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

    @app.patch("/workflow-templates/gallery/{entry_id}")
    def update_template_gallery_entry(
        entry_id: str,
        payload: TemplateGalleryUpdateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        entry = store.get_template_gallery_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        try:
            updated = store.update_template_gallery_entry(
                entry_id,
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                enabled=payload.enabled,
                client_id=entry.client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(updated)

    @app.get("/workflow-templates/gallery/{entry_id}/revisions")
    def template_gallery_revisions(
        entry_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            return []
        entry = store.get_template_gallery_entry(entry_id, scoped_client_id)
        if entry is None:
            return []
        return [
            _template_gallery_revision_view(revision)
            for revision in store.list_template_gallery_revisions(entry_id, entry.client_id)
        ]

    @app.get("/workflow-templates/gallery/{entry_id}/revisions/{version}/diff/{other_version}")
    def template_gallery_revision_diff(
        entry_id: str,
        version: int,
        other_version: int,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="template gallery revision not found")
        entry = store.get_template_gallery_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery revision not found")
        left = store.get_template_gallery_revision(entry_id, version, entry.client_id)
        right = store.get_template_gallery_revision(entry_id, other_version, entry.client_id)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="template gallery revision not found")
        return _template_gallery_revision_diff_view(left, right)

    @app.post("/workflow-templates/gallery/{entry_id}/revisions/{version}/restore")
    def restore_template_gallery_revision(
        entry_id: str,
        version: int,
        payload: TemplateGalleryRestoreRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, payload.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        entry = store.get_template_gallery_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        try:
            restored = store.restore_template_gallery_revision(entry_id, version, entry.client_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="template gallery revision not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="template gallery revision is no longer valid") from exc
        return _template_gallery_view(restored)

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
        if not entry.enabled:
            raise HTTPException(status_code=409, detail="template gallery entry is disabled")
        if store.get_ticket(request.ticket_id, client_id=scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        source_template = get_workflow_template(entry.source_template_id)
        if source_template is None:
            raise HTTPException(status_code=409, detail="source workflow template is unavailable")
        try:
            run = run_workflow_template(
                store,
                entry.source_template_id,
                request.ticket_id,
                client_id=scoped_client_id,
                actor=context.approver_id or "api",
                trigger_source="template_gallery",
                tool_executor=smart_action_service,
                template_override=replace(
                    source_template,
                    name=entry.name,
                    description=entry.description,
                ),
                operator_instructions=entry.instructions,
                template_version=entry.version,
                input_payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _dispatch_workflow_completion_event(event_dispatcher, run, context.approver_id or "api")
        return asdict(run)

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
        if request.report_type is not None:
            return _create_scheduled_report_job(request, context)
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
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_report_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if request.template_id is not None or request.agent_id is not None or request.entity_id is not None:
            raise HTTPException(status_code=422, detail="report schedules cannot include a workflow or agent target")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = _report_client_scope(context, requested_client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required for a scheduled report")
        params = dict(request.params)
        params["client_id"] = scoped_client_id
        try:
            validate_scheduled_report_params(params, timezone=request.timezone)
            scheduled_job = scheduler.register(
                request.report_type or "",
                request.cron,
                params,
                job_kind="report",
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
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
                timezone=request.timezone,
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
                    timezone=payload.timezone,
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
        scoped_client_id = _smart_action_client_scope(context, request.client_id)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        if store.get_ticket(request.ticket_id, client_id=scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        try:
            run = run_workflow_template(
                store,
                template_id,
                request.ticket_id,
                client_id=scoped_client_id,
                actor=context.approver_id or "api",
                trigger_source="api",
                tool_executor=smart_action_service,
                input_payload=request.payload,
            )
            _dispatch_workflow_completion_event(event_dispatcher, run, context.approver_id or "api")
            return asdict(run)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workflow template not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/workflow-runs")
    def workflow_runs(
        _: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [asdict(run) for run in store.list_workflow_runs(client_id=client_id)]

    @app.get("/workflow-runs/{run_id}")
    def workflow_run_detail(run_id: int, context: ViewerAccess) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        run = store.get_workflow_run(run_id, client_id=scoped_client_id)
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

    @app.get("/workflow-runs/{run_id}/compare/{other_run_id}")
    def workflow_run_compare(
        run_id: int,
        other_run_id: int,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scoped_client_id = _smart_action_client_scope(context, None)
        if context.role < Role.ADMIN and scoped_client_id is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        left = store.get_workflow_run(run_id, client_id=scoped_client_id)
        right = store.get_workflow_run(other_run_id, client_id=scoped_client_id)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return _workflow_run_comparison_view(left, right)

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
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
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

    def _syncro_comments_response(
        read_type: str, response: SyncroCommentsResponse
    ) -> dict[str, object]:
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
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
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
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _audit_confluence_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("confluence.read", read_type, f"{status} count={count}")

    def _notion_response(read_type: str, response: NotionReadResponse) -> dict[str, object]:
        _audit_notion_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _notion_data_source_response(
        read_type: str, response: NotionDataSourceResponse
    ) -> dict[str, object]:
        _audit_notion_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
        }

    def _audit_notion_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("notion.read", read_type, f"{status} count={count}")

    def _sharepoint_response(
        read_type: str,
        response: SharePointReadResponse,
    ) -> dict[str, object]:
        _audit_sharepoint_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _audit_sharepoint_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("sharepoint.read", read_type, f"{status} count={count}")

    def _scalepad_response(
        read_type: str,
        response: ScalePadClientResponse,
    ) -> dict[str, object]:
        _audit_scalepad_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _audit_scalepad_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("scalepad.read", read_type, f"{status} count={count}")

    def _m365_response(
        read_type: str,
        response: M365GraphReadResponse,
    ) -> dict[str, object]:
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _audit_m365_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("m365.read", read_type, f"{status} count={count}")

    def _m365_group_response(
        read_type: str,
        response: M365GraphGroupReadResponse,
    ) -> dict[str, object]:
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_license_response(
        read_type: str,
        response: M365GraphLicenseReadResponse,
    ) -> dict[str, object]:
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_license_detail_response(
        read_type: str,
        response: M365GraphLicenseDetailReadResponse,
    ) -> dict[str, object]:
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_mail_folder_response(
        read_type: str,
        response: M365GraphMailFolderReadResponse,
    ) -> dict[str, object]:
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_mail_message_response(
        read_type: str,
        response: M365GraphMailMessageReadResponse,
    ) -> dict[str, object]:
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

    def _m365_managed_device_response(
        read_type: str,
        response: M365GraphManagedDeviceReadResponse,
    ) -> dict[str, object]:
        _audit_m365_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [asdict(item) for item in response.items],
            "next_cursor": response.next_cursor,
        }

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
        if request.action_type.startswith("m365."):
            if request.status != "approved":
                return False, "Approval must be approved before execution."
            if request.execution_status == "succeeded":
                return False, "Approval request has already executed successfully."
            write_health = m365_client.write_health()
            if write_health.status != "ready":
                return False, write_health.message
            return True, ""
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
            "timezone": job.timezone,
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
                "execution_window_start": definition.execution_window_start,
                "execution_window_end": definition.execution_window_end,
                "execution_window_timezone": definition.execution_window_timezone,
                "context_sources": definition.context_sources,
                "approval_expiry_seconds": definition.approval_expiry_seconds,
                "result_aware": definition.result_aware,
                "approval_required_tools": definition.approval_required_tools,
                "approval_rules": definition.approval_rules,
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
        "agent_attempts": _safe_redacted_json_object(delivery.agent_attempts_json),
        "retry_count": delivery.retry_count,
        "max_retries": delivery.max_retries,
        "retry_delay_seconds": delivery.retry_delay_seconds,
        "next_retry_at": delivery.next_retry_at,
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
        "instructions": redact_text(entry.instructions),
        "enabled": entry.enabled,
        "version": entry.version,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "client_id": entry.client_id,
    }


def _template_gallery_export_view(entry) -> dict[str, object]:
    """Return a portable artifact without local ids, timestamps, or tenant identity."""

    return {
        "format": "wait-local-agent.workflow-template",
        "format_version": 1,
        "source_template_id": entry.source_template_id,
        "name": redact_text(entry.name),
        "description": redact_text(entry.description),
        "provenance": redact_text(entry.provenance),
        "instructions": redact_text(entry.instructions),
        "enabled": entry.enabled,
    }


def _template_gallery_revision_view(revision) -> dict[str, object]:
    return {
        "id": revision.id,
        "gallery_id": revision.gallery_id,
        "version": revision.version,
        "definition": _safe_redacted_json_object(revision.definition_json),
        "created_at": revision.created_at,
        "client_id": revision.client_id,
    }


def _workflow_run_comparison_view(left: WorkflowRun, right: WorkflowRun) -> dict[str, object]:
    fields = (
        "template_id",
        "ticket_id",
        "status",
        "message",
        "approval_request_id",
        "template_version",
        "client_id",
    )
    left_view = asdict(left)
    right_view = asdict(right)
    left_view["message"] = redact_text(left.message)
    right_view["message"] = redact_text(right.message)
    changes = [
        {"field": field, "before": left_view[field], "after": right_view[field]}
        for field in fields
        if left_view[field] != right_view[field]
    ]
    return {
        "from_run": left_view,
        "to_run": right_view,
        "changed": bool(changes),
        "changes": changes,
    }


def _template_gallery_revision_diff_view(left, right) -> dict[str, object]:
    left_definition = _safe_redacted_json_object(left.definition_json)
    right_definition = _safe_redacted_json_object(right.definition_json)
    changed_fields: list[dict[str, object]] = []
    for field in sorted(set(left_definition) | set(right_definition)):
        before = left_definition.get(field)
        after = right_definition.get(field)
        if before != after:
            changed_fields.append({"field": field, "before": before, "after": after})
    return {
        "gallery_id": left.gallery_id,
        "from_version": left.version,
        "to_version": right.version,
        "changed": bool(changed_fields),
        "changes": changed_fields,
        "client_id": left.client_id,
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
        "max_concurrency": backfill.max_concurrency,
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


def _end_user_ticket_view(ticket) -> dict[str, object]:
    return {
        "ticket_id": ticket.id,
        "subject": redact_text(ticket.subject),
        "body": redact_text(ticket.body),
        "status": ticket.status,
        "priority": ticket.priority,
    }


def _end_user_branding_text(value: str, fallback: str) -> str:
    cleaned = redact_text(value.strip())[:120].strip()
    return cleaned or fallback


_END_USER_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
_END_USER_LOGO_PATTERN = re.compile(
    r"^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$"
)


def _end_user_brand_color(value: str, fallback: str) -> str:
    cleaned = value.strip()
    return cleaned if _END_USER_COLOR_PATTERN.fullmatch(cleaned) else fallback


def _end_user_brand_logo_data_uri(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > 1_000_000 or not _END_USER_LOGO_PATTERN.fullmatch(cleaned):
        return ""
    return cleaned


def _end_user_message_view(message) -> dict[str, object]:
    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "body": redact_text(message.body),
        "role": "support" if message.author_role == "support" else "requester",
        "created_at": message.created_at,
    }


def _operator_end_user_message_view(message) -> dict[str, object]:
    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "role": "support" if message.author_role == "support" else "requester",
        "body": redact_text(message.body),
        "created_at": message.created_at,
    }


def _technician_chat_session_view(store: Store, session) -> dict[str, object]:
    return {
        "id": session.id,
        "status": session.status,
        "ticket_id": session.ticket_id,
        "client_id": session.client_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "message": redact_text(message.message),
                "action_id": message.action_id,
                "status": message.status,
                "ticket_id": message.ticket_id,
                "created_at": message.created_at,
            }
            for message in store.list_technician_chat_messages(
                session.id,
                client_id=session.client_id,
            )
        ],
    }


def _invoke_technician_chat_message(
    store: Store,
    smart_action_service: SmartActionService,
    agent_service: AgentService,
    message: str,
    *,
    ticket_id: str | None,
    actor: str,
    client_id: str | None,
    session_id: str | None = None,
    principal_id: str | None = None,
) -> dict[str, object]:
    if session_id is not None:
        store.add_technician_chat_message(
            session_id,
            role="user",
            message=message,
            status="received",
            ticket_id=ticket_id,
            client_id=client_id,
            principal_id=principal_id,
        )
    try:
        command = parse_technician_message(message, ticket_id=ticket_id)
    except TechnicianChatParseError as exc:
        if session_id is not None:
            store.add_technician_chat_message(
                session_id,
                role="assistant",
                message=str(exc),
                status="failed",
                ticket_id=ticket_id,
                client_id=client_id,
                principal_id=principal_id,
            )
        raise
    candidate_ticket_id = command.payload.get("ticket_id")
    resolved_ticket_id = candidate_ticket_id if isinstance(candidate_ticket_id, str) else None
    if session_id is not None and resolved_ticket_id and client_id:
        if (
            store.update_technician_chat_session_ticket(
                session_id,
                client_id=client_id,
                ticket_id=resolved_ticket_id,
                principal_id=principal_id,
            )
            is None
        ):
            raise LookupError(resolved_ticket_id)
    if command.mode == "help":
        if session_id is not None:
            store.add_technician_chat_message(
                session_id,
                role="assistant",
                message=command.reply,
                status="help",
                ticket_id=resolved_ticket_id,
                client_id=client_id,
                principal_id=principal_id,
            )
        response: dict[str, object] = {
            "status": "help",
            "message": command.reply,
            "supported": True,
        }
        if session_id is not None:
            response["session_id"] = session_id
        return response
    if command.mode == "plan":
        if not resolved_ticket_id:  # pragma: no cover - parser guarantees a plan ticket ID
            raise TechnicianChatParseError("include a ticket ID such as TCK-1001")
        try:
            plan = agent_service.plan(
                command.instruction or message,
                entity_id=resolved_ticket_id,
                client_id=client_id,
            )
        except AgentDefinitionError as exc:
            plan_message = f"The plan is blocked: {redact_text(str(exc))}"
            plan_payload: dict[str, object] = {
                "instruction": command.instruction or message,
                "entity_id": resolved_ticket_id,
                "client_id": client_id,
                "status": "blocked",
                "steps": [],
                "blocked_reason": redact_text(str(exc)),
            }
            plan_status = "blocked"
        else:
            plan_payload = asdict(plan)
            plan_status = plan.status
            plan_message = (
                "I prepared a bounded plan preview. Review the selected tools and approvals "
                "before creating or running an agent."
                if plan.status == "preview"
                else f"The plan is blocked: {plan.blocked_reason}"
            )
        _record_technician_chat_assistant(
            store,
            session_id=session_id,
            message=plan_message,
            status=plan_status,
            ticket_id=resolved_ticket_id,
            client_id=client_id,
            principal_id=principal_id,
        )
        response = {
            "status": plan_status,
            "message": plan_message,
            "plan": redact_value(plan_payload),
            "supported": True,
        }
        response.update({"session_id": session_id} if session_id is not None else {})
        return response
    action_id = command.action_id
    if not action_id:  # pragma: no cover - parser assigns an action for this mode
        raise TechnicianChatParseError("technician request did not select an approved action")
    result = smart_action_service.invoke(
        action_id,
        command.payload,
        actor,
        client_id=client_id,
    )
    _record_technician_chat_assistant(
        store,
        session_id=session_id,
        message=command.reply,
        action_id=action_id,
        status=result.status,
        ticket_id=resolved_ticket_id,
        client_id=client_id,
        principal_id=principal_id,
    )
    response = {
        "status": result.status,
        "message": command.reply,
        "action_id": action_id,
        "result": asdict(result),
    }
    if session_id is not None:
        response["session_id"] = session_id
    return response


def _record_technician_chat_assistant(
    store: Store,
    *,
    session_id: str | None,
    message: str,
    status: str,
    ticket_id: str | None,
    client_id: str | None,
    principal_id: str | None,
    action_id: str | None = None,
) -> None:
    if session_id is None:
        return
    store.add_technician_chat_message(
        session_id,
        role="assistant",
        message=message,
        action_id=action_id,
        status=status,
        ticket_id=ticket_id,
        client_id=client_id,
        principal_id=principal_id,
    )


def _safe_end_user_ticket_id(ticket_id: str) -> bool:
    return bool(
        ticket_id
        and len(ticket_id) <= 100
        and not any(ord(character) < 32 or character.isspace() for character in ticket_id)
    )


def _safe_external_ticket_id(ticket_id: str) -> bool:
    return bool(ticket_id.strip()) and len(ticket_id) <= 100 and all(
        ord(character) >= 32 and character not in "/?#\x00" for character in ticket_id
    )


def _halopsa_client_mapping(settings: Settings, client_id: str | None) -> str | None:
    normalized_client_id = _normalize_client_id(client_id)
    if normalized_client_id is None:
        return None
    try:
        payload = json.loads(settings.halopsa_client_map_json or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    mapped = payload.get(normalized_client_id)
    if isinstance(mapped, bool) or not isinstance(mapped, (str, int)):
        return None
    value = str(mapped).strip()
    return value or None


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
        "metadata": _safe_redacted_json_object(run.metadata_json),
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


def _dispatch_workflow_completion_event(
    event_dispatcher: EventDispatcher,
    run: WorkflowRun,
    actor: str,
) -> None:
    """Continue completed API workflow runs without changing their outcome."""
    if run.status != "completed" or run.id is None or not run.ticket_id.strip():
        return
    payload: dict[str, object] = {
        "workflow_run_id": str(run.id),
        "workflow_template_id": run.template_id,
        "status": run.status,
    }
    try:
        event_dispatcher.dispatch(
            event_type="workflow.completed",
            entity_type="ticket",
            entity_id=run.ticket_id,
            payload=payload,
            idempotency_key=f"workflow-completed:{run.id}",
            client_id=run.client_id,
            actor=actor,
        )
        event_dispatcher.store.add_audit_event(
            "workflow.completion_dispatched",
            str(run.id),
            "workflow.completed event dispatched",
            client_id=run.client_id,
        )
    except Exception as exc:  # noqa: BLE001 - completion must not be undone
        detail = redact_text(f"workflow.completed dispatch failed: {exc}")
        event_dispatcher.store.add_audit_event(
            "workflow.completion_dispatch_failed",
            str(run.id),
            detail,
            client_id=run.client_id,
        )


def _empty_analytics_summary(
    started_from: str | None, started_to: str | None
) -> dict[str, object]:
    return {
        "range": {"from": started_from, "to": started_to},
        "client_id": None,
        "executions_over_time": [],
        "success_rate": {"total": 0, "succeeded": 0, "rate": 0.0},
        "failures_by_status": [],
        "approval_rate": {
            "requested": 0,
            "decided": 0,
            "approved": 0,
            "rejected": 0,
            "pending": 0,
            "rate": 0.0,
            "derivation": APPROVAL_RATE_DERIVATION,
        },
        "ticket_metrics": {
            "touched": 0,
            "resolved": 0,
            "resolution_rate": 0.0,
            "derivation": TICKET_METRICS_DERIVATION,
            "historical_resolution": {
                "resolved_with_history": 0,
                "with_duration": 0,
                "average_minutes": None,
                "derivation": TICKET_LIFECYCLE_DERIVATION,
            },
        },
        "activity_by_workflow": [],
        "estimated_minutes_saved": {
            "minutes": 0,
            "estimate": True,
            "derivation": ESTIMATED_MINUTES_SAVED_DERIVATION,
        },
        "model_usage": {
            "runs_with_usage": 0,
            "runs_with_cost": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "estimate": True,
            "derivation": MODEL_COST_DERIVATION,
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


def _report_client_scope(context: AuthContext, requested_client_id: str | None) -> str | None:
    """Require a tenant for non-admin report reads and generation."""

    scoped_client_id = _smart_action_client_scope(context, requested_client_id)
    if context.role < Role.ADMIN and scoped_client_id is None:
        raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
    return scoped_client_id


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


def _connectwise_draft_view(draft) -> dict[str, object]:
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
