from __future__ import annotations

import csv
import io
import json
import logging
import os
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from packs.microsoft_admin.client import MicrosoftAdminGraphClient
from wait_local_agent import __version__
from wait_local_agent.agents import AgentDefinitionError, AgentService
from wait_local_agent.api.auth_routes import create_auth_router
from wait_local_agent.api.context import (
    AdminAccess,
    ApiContext,
    EndUserAccess,
    TechnicianAccess,
    ViewerAccess,
)
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
    configure_pack_routes,
)
from wait_local_agent.api.routers import mount_flat
from wait_local_agent.api.routers.documentation_connectors import create_documentation_connectors_router
from wait_local_agent.api.routers.m365 import create_m365_router
from wait_local_agent.api.routers.psa_connectors import create_psa_connectors_router
from wait_local_agent.api.routers.system import create_system_router
from wait_local_agent.api.schemas import (
    AgentApprovalRuleRequest,  # noqa: F401
    AgentBackfillCreateRequest,
    AgentBackfillPreviewRequest,
    AgentDefinitionRequest,
    AgentPlanRequest,
    AgentRunStartRequest,
    AgentStepRequest,  # noqa: F401
    ApprovalPayloadPatchRequest,
    ApprovalRequest,
    BackupCreateRequest,
    BackupRestoreRequest,
    ClientConnectorMappingCreateRequest,
    ClientCreateRequest,
    ClientDiscoveryBulkAcceptRequest,
    ClientDiscoveryRunRequest,
    ClientReportRequest,
    ClientStatusRequest,
    CollectorConfigRequest,
    CollectorRunRequest,
    ConnectorInstanceCreateRequest,
    ConnectorInstanceUpdateRequest,
    CopilotStudioPlanRequest,
    DeliveryPlanRequest,
    DeploymentModeRequest,
    DiagnosticsBundleRequest,
    DiagnosticsUploadRequest,
    DiscoveryBlueprintPromotionRequest,
    DiscoveryRequest,
    DiscoverySessionStartRequest,
    DiscoveryTurnRequest,
    EmployeeOnboardingDemoRequest,
    EndUserBrandingResponse,
    EndUserHaloSyncDraftRequest,
    EndUserMessageRequest,
    EndUserTicketCreateRequest,
    EnvironmentDiscoveryRequest,
    EvaluationExecutionRequest,  # noqa: F401
    EvaluationRequest,
    EventIngestRequest,
    GovernanceRequest,
    HardeningRunRequest,
    KnowledgeAuthorityRequest,
    KnowledgeIngestRequest,
    MspPlaybookEntryCreateRequest,
    MspPlaybookEntryUpdateRequest,
    MspPlaybookRunRequest,
    MspPlaybookSubscriptionCreateRequest,
    MspPlaybookSubscriptionUpdateRequest,
    OpenApiConnectorRequest,
    PowerAppsPlanRequest,
    PowerAutomatePlanRequest,
    PowerPlatformDeploymentRequest,
    PowerPlatformPackageMaterializationRequest,
    PowerPlatformPackageRequest,
    PowerPlatformPackageValidationRequest,
    PowerPlatformRollbackRequest,
    QuarantineReclassificationRequest,
    RestoreExerciseRequest,
    ScheduledJobCreateRequest,
    ScheduledJobRescheduleRequest,
    SecretSetRequest,
    SmartActionInvokeRequest,
    SolutionBlueprintRequest,
    SupervisorPlanRequest,
    SupervisorRunRequest,
    TeamsMessageDraftRequest,  # noqa: F401
    TechnicianChatMessageRequest,
    TechnicianChatRequest,
    TechnicianChatSessionCreateRequest,
    TemplateGalleryCreateRequest,
    TemplateGalleryImportRequest,
    TemplateGalleryRestoreRequest,
    TemplateGalleryUpdateRequest,
    WorkflowRunRequest,
)
from wait_local_agent.api.scopes import (
    _approval_scope_visible,
    _backfill_scope,
    _connector_read_client,  # noqa: F401
    _end_user_client_id,
    _end_user_read_client_id,
    _operator_scope,
    _request_correlation_id,
    _require_commercial_activation_access,
    _require_msp_operator,
    _required_client_id,
    _resolve_client_target_scope,
    _resolve_detail_scope,
    _scheduled_job_for_context,
    _scope_contains_client,  # noqa: F401
    _singular_action_client,
)
from wait_local_agent.api.views import (
    _EXECUTING_EXECUTION_STATUS,  # noqa: F401
    _TERMINAL_EXECUTION_STATUSES,
    SENSITIVE_KEY_PARTS,  # noqa: F401
    _agent_backfill_view,
    _agent_definition_view,
    _agent_revision_diff_view,
    _agent_revision_view,
    _agent_run_view,
    _baseline_view,
    _dispatch_workflow_completion_event,
    _empty_analytics_summary,  # noqa: F401
    _end_user_brand_color,
    _end_user_brand_logo_data_uri,
    _end_user_branding_text,
    _end_user_message_view,
    _end_user_ticket_view,
    _event_delivery_view,
    _event_dispatch_view,
    _execution_artifact_view,
    _execution_run_view,
    _execution_step_view,
    _halopsa_client_mapping,
    _halopsa_draft_view,
    _invoke_technician_chat_message,
    _operator_end_user_message_view,
    _power_platform_source_record,
    _record_technician_chat_assistant,  # noqa: F401
    _redact_json_text,
    _redact_payload,
    _redact_request_input,
    _redact_value,  # noqa: F401
    _safe_end_user_ticket_id,
    _safe_external_ticket_id,
    _safe_json_list,  # noqa: F401
    _safe_json_object,
    _safe_json_value,  # noqa: F401
    _safe_json_values,
    _safe_redacted_json_object,  # noqa: F401
    _scheduled_job_view,
    _scheduled_ticket_id,
    _smart_action_run_view,
    _technician_chat_session_view,
    _template_gallery_export_view,
    _template_gallery_revision_diff_view,
    _template_gallery_revision_view,
    _template_gallery_view,
    _workflow_run_comparison_view,
    make_approval_view,
)
from wait_local_agent.autotask import AutotaskClient
from wait_local_agent.backup import (
    BackupEncryptionError,
    backup_state,
    restore_state,
    run_restore_exercise,
)
from wait_local_agent.baseline import BaselineService
from wait_local_agent.client_discovery import (
    PSA_CONNECTOR_TYPES,
    ClientDiscoveryError,
    assert_bulk_accept_allowed,
    discover_instance,
)
from wait_local_agent.client_scope import (
    AllClients,
    BoundClients,
    ClientScope,
    requested_client_from,
    resolve_client_scope,
)
from wait_local_agent.collectors import (
    CollectorService,
    collector_run_collection_scope,
    collector_run_result_status,
    default_registry,
)
from wait_local_agent.communication import ConfiguredCommunicationProvider
from wait_local_agent.config import (
    Settings,
    load_settings,
    validate_secrets_backend_configuration,
)
from wait_local_agent.confluence import ConfluenceClient
from wait_local_agent.connector_factory import (
    SUPPORTED_CONNECTOR_TYPES,
    ConnectorFactoryError,
    build_read_client_for_client,  # noqa: F401
    validate_connector_instance,
)
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_connectwise_approval_request,
    execute_halopsa_approval_request,
    execute_m365_approval_request,
    list_connector_statuses,
    list_secret_records,
    probe_connector_health,
    update_connectwise_approval_fields,
    update_halopsa_approval_fields,
)
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.consultant import (
    BlueprintValidationError,
    architect_solution_blueprint,
    blueprint_payload,
    blueprint_view,
    generate_playbook_from_blueprint,
    parse_solution_blueprint,
    promote_discovery_candidate,
)
from wait_local_agent.consultant_use_cases import UseCaseCatalogError, list_consultant_use_cases
from wait_local_agent.copilot_studio import CopilotStudioPlanError, build_copilot_studio_plan
from wait_local_agent.delivery_plan import DeliveryPlanError, build_consultant_delivery_plan
from wait_local_agent.diagnostics import (
    BundleLimitError,
    build_support_bundle,
    collect_diagnostics,
    preview_support_bundle,
    support_upload_refusal,
    valid_correlation_id,
)
from wait_local_agent.diagnostics import (
    scrub_text as scrub_diagnostic_text,
)
from wait_local_agent.discovery import (
    DiscoveryValidationError,
    build_solution_discovery,
    discover_solution_environment,
)
from wait_local_agent.employee_onboarding_demo import (
    EmployeeOnboardingDemoError,
    run_employee_onboarding_demo,
)
from wait_local_agent.evaluation import (
    AgentServiceEvaluationExecutor,
    EvaluationValidationError,
    evaluate_tool_contract,
    execute_tool_contract,
)
from wait_local_agent.event_dispatch import EventDispatcher, EventDispatchError
from wait_local_agent.founder_bundle import PrivacyViolation
from wait_local_agent.governance import GovernanceValidationError, evaluate_solution_governance
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.hudu import HuduClient
from wait_local_agent.ingestion_poller import IngestionPoller
from wait_local_agent.itglue import ItGlueClient
from wait_local_agent.knowledge import ingestion_service_from_settings
from wait_local_agent.lp_client import (
    LaunchPassportError,
    LaunchPassportForbidden,
    LaunchPassportPayloadTooLarge,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
)
from wait_local_agent.m365_auth import M365ConnectionResolver, M365ProfileResolutionError
from wait_local_agent.m365_graph import (
    M365GraphClient,
)
from wait_local_agent.mcp import (
    MAX_MCP_REQUEST_BYTES,
    MCP_PROTOCOL_VERSION,
    McpProtocolError,
    WaitMcpServer,
    origin_allowed,
    protocol_error_response,
)
from wait_local_agent.models import (
    AGENT_BACKFILL_MAX_CONCURRENCY,
    AgentDefinition,
    ClientCandidate,
    ConnectorInstance,
    ConsultantDiscoverySession,
)
from wait_local_agent.monitoring import build_agent_health_summary
from wait_local_agent.msp_playbooks import (
    create_msp_playbook_subscription,
    list_msp_playbooks,
    msp_playbook_entry_view,
    msp_playbook_revision_diff,
    msp_playbook_revision_view,
    msp_playbook_subscription_view,
    playbook_view,
    preview_msp_playbook,
    publish_msp_playbook,
    run_msp_playbook,
    update_msp_playbook,
    update_msp_playbook_subscription,
)
from wait_local_agent.notion import NotionClient
from wait_local_agent.observability import (
    build_analytics_summary,
)
from wait_local_agent.oidc import get_or_create_session_signing_key
from wait_local_agent.operational_graph import OperationalGraphService
from wait_local_agent.power_apps import (
    PowerAppsPlanError,
    build_power_apps_artifact,
    build_power_apps_plan,
)
from wait_local_agent.power_automate import PowerAutomatePlanError, build_power_automate_flow_plan
from wait_local_agent.power_platform import (
    OpenApiDefinitionError,
    compare_pac_versions,
    generate_power_platform_connector,
    power_platform_cli_status,
)
from wait_local_agent.power_platform_deployment import (
    PowerPlatformDeploymentError,
    build_power_platform_deployment_plan,
    build_power_platform_deployment_plan_from_payload,
    execute_power_platform_rollback,
    execute_power_platform_stage,
    validate_power_platform_solution_package,
    validate_promotion_evidence,
    validate_promotion_source,
    validate_rollback_evidence,
)
from wait_local_agent.power_platform_package import (
    PAC_XML_MINIMUM_VERSION,
    PowerPlatformPackageError,
    build_power_platform_package,
    materialize_power_platform_package,
    package_validation_result,
)
from wait_local_agent.providers import (
    provider_from_settings,
)
from wait_local_agent.rbac import (
    AuthContext,
    Role,
    admin_credential_configured,
    require_role,
    resolve_auth_context,
)
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
from wait_local_agent.reports.renderers import redact_text, report_as_dict
from wait_local_agent.reports.service import ReportService
from wait_local_agent.rmm import RmmProviderResolutionError, rmm_provider_from_settings
from wait_local_agent.scalepad import (
    ScalePadClient,
)
from wait_local_agent.scheduler import SchedulerManager, validate_scheduled_report_params
from wait_local_agent.servicenow import ServiceNowClient
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.sessions import SESSION_COOKIE_NAME
from wait_local_agent.sharepoint import SharePointClient
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.spa_routes import SPA_ROUTE_PATHS
from wait_local_agent.store import (
    _QUARANTINE_CLIENT_ID,
    ClientConnectorMappingConflictError,
    QuarantinedTicketError,
    QuarantineRetenantStateError,
    QuarantineRetenantTargetError,
    Store,
    _normalize_client_id,
)
from wait_local_agent.supervisor import (
    SupervisorPlanError,
    build_supervisor_delegation_plan,
    execute_supervisor_delegation,
)
from wait_local_agent.syncro import SyncroClient
from wait_local_agent.teams_graph import TeamsGraphClient
from wait_local_agent.technician_chat import TechnicianChatParseError
from wait_local_agent.timezest import TimeZestClient
from wait_local_agent.update_channel import UpdateStatusCache
from wait_local_agent.vault import SecretVault, SecretVaultError
from wait_local_agent.vector_search import search_backend_from_settings
from wait_local_agent.workflow_designer import (
    WorkflowDesignError,
    default_workflow_design,
)
from wait_local_agent.workflows import (
    get_workflow_template,
    list_workflow_templates,
    run_workflow_template,
)
from wait_local_agent.workiq import WorkIqClient

LOGGER = logging.getLogger(__name__)
CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get(CORRELATION_HEADER)
        correlation_id = str(supplied) if valid_correlation_id(supplied) else uuid.uuid4().hex
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        status_code = 500

        async def send_with_correlation(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            LOGGER.info(
                "request completed method=%s status=%d",
                scope.get("method", ""),
                status_code,
                extra={"correlation_id": correlation_id},
            )


class SPAStaticFiles(StaticFiles):
    """Serve compiled assets and fall back to the dashboard entrypoint."""

    def __init__(self, *, directory: Path) -> None:
        super().__init__(directory=directory)
        self.index_path = directory / "index.html"

    async def get_response(self, path: str, scope: Scope) -> Response:
        # The API is intentionally not mounted below /api today, but reserve
        # that namespace so a future API route cannot be hidden by the SPA.
        reserved_prefixes = ("api", "docs", "packs")
        reserved = path == "openapi.json" or any(
            path == prefix or path.startswith(f"{prefix}/") for prefix in reserved_prefixes
        )

        try:
            response = await super().get_response(path, scope)
            if path in {"", "index.html"}:
                _set_spa_html_headers(response)
            elif path.startswith("assets/"):
                _set_hashed_asset_headers(response)
            return response
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in {"GET", "HEAD"} or reserved:
                raise

        return _spa_index_response(self.index_path)


class SPAHtmlRoutesMiddleware:
    """Serve the SPA entrypoint for browser requests to known UI routes."""

    def __init__(self, app: ASGIApp, *, index_path: Path, route_paths: frozenset[str]) -> None:
        self.app = app
        self.index_path = index_path
        self.route_paths = route_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["method"] not in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        if path not in self.route_paths:
            await self.app(scope, receive, send)
            return

        request_headers = Headers(scope=scope)
        has_authenticated_request = (
            request_headers.get("authorization") is not None
            or _has_session_cookie(request_headers.get("cookie"))
        )

        accept = next(
            (value for name, value in scope["headers"] if name == b"accept"),
            b"",
        ).decode("latin-1").lower()
        if "text/html" not in accept:
            async def send_with_cache_headers(message: Message) -> None:
                if message["type"] == "http.response.start":
                    response_headers = MutableHeaders(scope=message)
                    vary = response_headers.get("Vary")
                    if vary and "accept" not in {value.strip().lower() for value in vary.split(",")}:
                        response_headers["Vary"] = f"{vary}, Accept"
                    else:
                        response_headers["Vary"] = "Accept"
                    content_type = response_headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    is_json_response = content_type == "application/json" or content_type.endswith("+json")
                    if has_authenticated_request and is_json_response:
                        response_headers["Cache-Control"] = "no-store"
                await send(message)

            await self.app(scope, receive, send_with_cache_headers)
            return

        await _spa_index_response(self.index_path)(scope, receive, send)


def _has_session_cookie(cookie_header: str | None) -> bool:
    # The browser session cookie is SESSION_COOKIE_NAME ("wait_session"); the OIDC transaction
    # cookie only exists mid-login, but a response carrying it is also user-specific.
    return any(
        part.strip().partition("=")[0] in {SESSION_COOKIE_NAME, "wait_oidc_txn"}
        for part in (cookie_header or "").split(";")
    )


def _set_spa_html_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Accept"


def _set_hashed_asset_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"


def _spa_index_response(index_path: Path) -> FileResponse:
    return FileResponse(
        index_path,
        media_type="text/html",
        headers={"Cache-Control": "no-store", "Vary": "Accept"},
    )


def _resolve_ui_dist() -> Path | None:
    ui_dist_value = os.getenv("WAIT_UI_DIST", "").strip()
    if not ui_dist_value:
        return None
    ui_dist = Path(ui_dist_value)
    if not ui_dist.is_dir() or not (ui_dist / "index.html").is_file():
        return None
    return ui_dist


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or load_settings()
    validate_secrets_backend_configuration(active_settings)
    if active_settings.demo_mode:
        active_settings = replace(
            active_settings,
            allow_write_actions=False,
            allow_power_platform_deployment=False,
        )
    store = Store(active_settings.data_path)
    vault = SecretVault(active_settings.vault_path)
    m365_connection_resolver = M365ConnectionResolver(active_settings, store, vault)
    session_signing_key = get_or_create_session_signing_key(active_settings, vault)
    if not active_settings.demo_mode and not admin_credential_configured(active_settings, store):
        raise RuntimeError(
            "refusing non-demo startup without an admin credential; configure WAIT_ADMIN_TOKEN or "
            "WAIT_API_TOKEN, or provision an active msp_admin principal credential"
        )
    service = TicketIntelligenceService(
        store=store,
        settings=active_settings,
        provider=provider_from_settings(active_settings),
    )
    rmm_provider = rmm_provider_from_settings(active_settings, store, allow_msp_wide=True)
    operational_graph_service = OperationalGraphService(store, rmm_provider=rmm_provider)
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
    # Keep construction compatible with injected test clients while making the
    # runtime Graph client use the same profile resolver as the admin pack.
    m365_client.connection_resolver = m365_connection_resolver
    teams_client = TeamsGraphClient(active_settings)
    work_iq_client = WorkIqClient(active_settings)
    update_status_cache = UpdateStatusCache(ttl_seconds=3600.0)
    report_service = ReportService(store)
    collector_service = CollectorService(store, default_registry)
    smart_action_service = SmartActionService(
        store,
        active_settings,
        collector_service=collector_service,
        rmm_provider=rmm_provider,
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
        teams_client=teams_client,
        timezest_client=timezest_client,
        scalepad_client=scalepad_client,
        m365_client=m365_client,
        work_iq_client=work_iq_client,
        communication_provider=ConfiguredCommunicationProvider(active_settings),
    )
    agent_service = AgentService(store, active_settings, smart_action_service)
    mcp_server = WaitMcpServer(agent_service, smart_action_service)
    event_dispatcher = EventDispatcher(store, agent_service)

    def _m365_graph_client_for_client(client_id: str) -> M365GraphClient:
        connection = m365_connection_resolver.resolve(client_id)
        return M365GraphClient(
            active_settings,
            connection=connection,
            client_id=client_id,
        )

    def _m365_graph_service_for_client(client_id: str) -> OperationalGraphService:
        return OperationalGraphService(store, m365_client=_m365_graph_client_for_client(client_id))

    def _microsoft_admin_client_for_client(client_id: str) -> MicrosoftAdminGraphClient:
        return MicrosoftAdminGraphClient(
            active_settings,
            connection_resolver=m365_connection_resolver,
            client_id=client_id,
        )

    baseline_service = BaselineService(
        store,
        microsoft_provider_factory=_microsoft_admin_client_for_client,
        core_client_factory=_m365_graph_client_for_client,
    )

    def _run_client_graph_sync(client_id: str) -> object:
        client = store.get_client(AllClients(), client_id)
        if client is None or client.status.strip().lower() != "active":
            raise ValueError("client must be active")
        try:
            client_rmm_provider = rmm_provider_from_settings(active_settings, store, client_id, vault)
        except RmmProviderResolutionError as exc:
            raise ValueError(str(exc)) from exc
        if client_rmm_provider.adapter_id != "local-collector" and not active_settings.allow_http_probing:
            raise ValueError("RMM read probing is disabled")
        return OperationalGraphService(
            store,
            rmm_provider=client_rmm_provider,
            m365_client=_m365_graph_client_for_client(client_id),
        ).seed_client_inventory(client_id)

    scheduler = SchedulerManager(
        store,
        enabled=active_settings.scheduler_enabled,
        agent_service=agent_service,
        smart_action_service=smart_action_service,
        event_dispatcher=event_dispatcher,
        ingestion_poller=IngestionPoller(store, base_settings=active_settings),
        graph_sync_runner=_run_client_graph_sync,
        baseline_snapshot_runner=lambda client_id: baseline_service.create_baseline(client_id),
        settings=active_settings,
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
        version=__version__,
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
    app.state.vault = vault
    app.state.m365_connection_resolver = m365_connection_resolver
    app.state.scheduler = scheduler
    app.state.limiter = limiter
    app.state.update_status_cache = update_status_cache
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_exception_handler(RequestValidationError, _request_validation_error_handler)
    app.add_exception_handler(QuarantinedTicketError, _quarantined_ticket_handler)
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
    ui_dist = _resolve_ui_dist()
    if ui_dist is not None:
        app.add_middleware(
            SPAHtmlRoutesMiddleware,
            index_path=ui_dist / "index.html",
            route_paths=SPA_ROUTE_PATHS,
        )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(active_settings.trusted_hosts),
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_signing_key,
        session_cookie="wait_oidc_txn",
        max_age=600,
        same_site="lax",
        https_only=active_settings.session_cookie_secure,
    )
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    configure_pack_routes(
        app,
        active_settings,
        route_dependencies=[Depends(require_role(Role.VIEWER))],
    )
    app.include_router(create_founder_router())
    app.include_router(create_auth_router(limiter))

    def _m365_health_configured() -> bool:
        try:
            return m365_connection_resolver.resolve(allow_msp_wide=True).token_provider.configured
        except Exception:
            # Health must remain available even when a stored profile is
            # malformed or ambiguous; the connector endpoint reports the
            # sanitized failure when it is used.
            return bool(active_settings.m365_graph_base_url and active_settings.m365_access_token)

    _connector_read_client = partial(  # noqa: F811
        globals()["_connector_read_client"],
        settings=active_settings,
        store=store,
        vault=vault,
        m365_connection_resolver=m365_connection_resolver,
    )

    _approval_view = make_approval_view(
        store=store,
        active_settings=active_settings,
        halopsa_client=halopsa_client,
        m365_client=m365_client,
        teams_client=teams_client,
    )

    ctx = ApiContext(
        active_settings=active_settings,
        store=store,
        vault=vault,
        app=app,
        limiter=limiter,
        service=service,
        rmm_provider=rmm_provider,
        operational_graph_service=operational_graph_service,
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
        teams_client=teams_client,
        update_status_cache=update_status_cache,
        report_service=report_service,
        collector_service=collector_service,
        smart_action_service=smart_action_service,
        agent_service=agent_service,
        mcp_server=mcp_server,
        event_dispatcher=event_dispatcher,
        baseline_service=baseline_service,
        scheduler=scheduler,
        m365_graph_service_for_client=_m365_graph_service_for_client,
        m365_health_configured=_m365_health_configured,
        connector_read_client=_connector_read_client,
        approval_view=_approval_view,
    )

    mount_flat(app, create_system_router(ctx))

    @app.get("/tickets")
    def tickets(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [asdict(ticket) for ticket in store.list_tickets(client_id=scope)]

    @app.get("/clients")
    def clients(context: ViewerAccess, client_id: str | None = None) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [asdict(client) for client in store.list_clients(scope)]

    @app.get("/clients/commercial-activations")
    def commercial_activations(context: AdminAccess) -> list[dict[str, object]]:
        _require_commercial_activation_access(context)
        return [asdict(activation) for activation in store.list_commercial_activations(AllClients())]

    def _discovery_summary() -> dict[str, int]:
        counts = store.count_client_candidates()
        return {
            "discovered": sum(
                counts.get(state, 0)
                for state in ("verified", "proposed", "ambiguous", "unmatched", "conflicting")
            ),
            "reconciled": counts.get("verified", 0),
            "need_confirmation": counts.get("proposed", 0) + counts.get("ambiguous", 0),
            "unmatched": counts.get("unmatched", 0),
            "conflicts": counts.get("conflicting", 0),
        }

    def _require_discovery_write(context: AuthContext) -> None:
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="client discovery is unavailable in demo mode")
        _require_msp_operator(context)

    @app.get("/setup/mode")
    def deployment_mode(_: ViewerAccess) -> dict[str, str | None]:
        mode = store.get_app_config("deployment.mode")
        return {"mode": mode if mode in {"msp", "smb"} else None}

    @app.put("/setup/mode")
    def set_deployment_mode(payload: DeploymentModeRequest, context: AdminAccess) -> dict[str, str]:
        _require_discovery_write(context)
        store.set_app_config("deployment.mode", payload.mode, updated_by=context.approver_id or "admin")
        store.add_audit_event(
            "deployment.mode.updated", "deployment.mode", f"mode={payload.mode}", approver_id=context.approver_id
        )
        return {"mode": payload.mode}

    @app.post("/discovery/clients/run")
    def run_client_discovery(payload: ClientDiscoveryRunRequest, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        instances = store.list_connector_instances()
        if payload.connector_instance_id:
            instance = store.get_connector_instance(payload.connector_instance_id)
            if instance is None:
                raise HTTPException(status_code=404, detail="connector instance not found")
            instances = [instance]
        instances = [
            instance for instance in instances if instance.connector_type.casefold().strip() in PSA_CONNECTOR_TYPES
        ]
        if payload.connector_instance_id and not instances:
            raise HTTPException(status_code=409, detail="connector instance is not a supported PSA instance")
        discovered: list[ClientCandidate] = []
        failures: list[dict[str, str]] = []
        for instance in instances:
            try:
                discovered.extend(discover_instance(store, instance, settings=active_settings, vault=vault))
            except ClientDiscoveryError as exc:
                failures.append({"connector_instance_id": instance.connector_instance_id, "detail": str(exc)})
        store.add_audit_event(
            "client.discovery.run",
            payload.connector_instance_id or "all",
            f"candidates={len(discovered)} failures={len(failures)}",
            approver_id=context.approver_id,
        )
        return {
            "candidates": [asdict(candidate) for candidate in discovered],
            "failures": failures,
            "summary": _discovery_summary(),
        }

    @app.get("/discovery/clients")
    def list_client_discovery_candidates(
        context: AdminAccess,
        match_state: Literal[
            "verified", "proposed", "ambiguous", "unmatched", "conflicting", "dismissed"
        ] | None = None,
        page: int = Query(default=1, ge=1, le=5000),
        page_size: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, object]:
        _require_discovery_write(context)
        candidates = store.list_client_candidates(
            match_state=match_state, offset=(page - 1) * page_size, limit=page_size
        )
        return {
            "items": [asdict(candidate) for candidate in candidates],
            "page": page,
            "page_size": page_size,
            "summary": _discovery_summary(),
        }

    def _accept_discovery_candidate(candidate: ClientCandidate, context: AuthContext) -> dict[str, object]:
        if candidate.match_state != "proposed" or not candidate.matched_client_id:
            raise HTTPException(
                status_code=409, detail="only proposed candidates with one matched client can be accepted"
            )
        if store.get_client(AllClients(), candidate.matched_client_id) is None:
            raise HTTPException(status_code=409, detail="the proposed client no longer exists")
        try:
            mapping = store.create_client_connector_mapping(
                AllClients(), candidate.connector_instance_id, candidate.external_id, candidate.matched_client_id,
                external_company_name=candidate.display_name,
            )
            verification = store.verify_client_connector_mapping(
                AllClients(), mapping.mapping_id, return_retenanted_count=True
            )
        except ClientConnectorMappingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (sqlite3.IntegrityError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="candidate mapping could not be created") from exc
        if not isinstance(verification, tuple):  # pragma: no cover
            raise RuntimeError("mapping verification did not return re-tenant count")
        verified_mapping, retenanted_count = verification
        updated = store.set_client_candidate_state(
            candidate.candidate_id, "verified", matched_client_id=verified_mapping.client_id,
            match_reason="accepted proposed exact normalized name", confidence=1.0,
        )
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="candidate not found")
        store.add_audit_event(
            "client.discovery.accepted",
            candidate.candidate_id,
            f"client={verified_mapping.client_id}",
            client_id=verified_mapping.client_id,
            approver_id=context.approver_id,
        )
        return {
            **asdict(updated),
            "mapping": asdict(verified_mapping),
            "retenanted_count": retenanted_count,
        }

    @app.post("/discovery/clients/{candidate_id}/accept")
    def accept_client_discovery_candidate(candidate_id: str, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        candidate = store.get_client_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        return _accept_discovery_candidate(candidate, context)

    @app.post("/discovery/clients/accept-proposed")
    def bulk_accept_client_discovery_candidates(
        payload: ClientDiscoveryBulkAcceptRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_discovery_write(context)
        candidates = [store.get_client_candidate(candidate_id) for candidate_id in payload.candidate_ids]
        if any(candidate is None for candidate in candidates):
            raise HTTPException(status_code=404, detail="candidate not found")
        resolved = cast(list[ClientCandidate], candidates)
        try:
            assert_bulk_accept_allowed(resolved)
        except ClientDiscoveryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        accepted = [_accept_discovery_candidate(candidate, context) for candidate in resolved]
        return {"accepted": accepted, "summary": _discovery_summary()}

    @app.post("/discovery/clients/{candidate_id}/create-client")
    def create_client_from_discovery_candidate(candidate_id: str, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        candidate = store.get_client_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        if candidate.match_state in {"verified", "dismissed"}:
            raise HTTPException(status_code=409, detail="candidate cannot create a client in its current state")
        client_id = f"discovered-{candidate.candidate_id.replace('-', '')[:24]}"
        try:
            client = store.create_client(client_id, candidate.display_name)
            mapping = store.create_client_connector_mapping(
                AllClients(), candidate.connector_instance_id, candidate.external_id, client.client_id,
                external_company_name=candidate.display_name,
            )
            verification = store.verify_client_connector_mapping(
                AllClients(), mapping.mapping_id, return_retenanted_count=True
            )
        except (sqlite3.IntegrityError, KeyError, ValueError, ClientConnectorMappingConflictError) as exc:
            raise HTTPException(status_code=409, detail="client or candidate mapping already exists") from exc
        if not isinstance(verification, tuple):  # pragma: no cover
            raise RuntimeError("mapping verification did not return re-tenant count")
        verified_mapping, retenanted_count = verification
        updated = store.set_client_candidate_state(
            candidate.candidate_id,
            "verified",
            matched_client_id=client.client_id,
            match_reason="new client created from provider candidate",
            confidence=1.0,
        )
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="candidate not found")
        store.add_audit_event(
            "client.discovery.created",
            candidate.candidate_id,
            f"client={client.client_id}",
            client_id=client.client_id,
            approver_id=context.approver_id,
        )
        return {
            **asdict(updated),
            "client": asdict(client),
            "mapping": asdict(verified_mapping),
            "retenanted_count": retenanted_count,
        }

    @app.post("/discovery/clients/{candidate_id}/dismiss")
    def dismiss_client_discovery_candidate(candidate_id: str, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        candidate = store.get_client_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        if candidate.match_state == "verified":
            raise HTTPException(status_code=409, detail="verified candidates cannot be dismissed")
        updated = store.set_client_candidate_state(candidate_id, "dismissed", match_reason="dismissed by administrator")
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="candidate not found")
        store.add_audit_event(
            "client.discovery.dismissed", candidate_id, "dismissed by administrator", approver_id=context.approver_id
        )
        return asdict(updated)

    @app.post("/clients")
    def create_client(payload: ClientCreateRequest, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        try:
            return asdict(store.create_client(payload.client_id, payload.name))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="client already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/clients/{client_id}")
    def client_detail(client_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_client_target_scope(context, client_id)
        client = store.get_client(scope, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        return asdict(client)

    @app.post("/clients/{client_id}/commercial-activation")
    def activate_commercial_client(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_commercial_activation_access(context)
        scope = _resolve_client_target_scope(context, client_id)
        try:
            activation = store.activate_commercial_client(
                scope,
                client_id,
                context.approver_id or "admin",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if activation is None:
            raise HTTPException(status_code=404, detail="client not found")
        store.add_audit_event(
            "commercial.client_activated",
            activation.client_id,
            "commercial managed-client bookkeeping activated",
            client_id=activation.client_id,
            approver_id=context.approver_id,
        )
        return asdict(activation)

    @app.delete("/clients/{client_id}/commercial-activation")
    def deactivate_commercial_client(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_commercial_activation_access(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        store.deactivate_commercial_client(scope, client_id)
        store.add_audit_event(
            "commercial.client_deactivated",
            client_id,
            "commercial managed-client bookkeeping deactivated",
            client_id=client_id,
            approver_id=context.approver_id,
        )
        return {"client_id": client_id.strip(), "commercial_managed": False}

    @app.post("/clients/{client_id}/baselines", status_code=201)
    def create_client_baseline(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        if active_settings.demo_mode or not active_settings.allow_write_actions:
            raise HTTPException(status_code=403, detail="baseline writes are unavailable in demo mode")
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            return _baseline_view(baseline_service.create_baseline(client_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # do not expose provider failures
            raise HTTPException(status_code=503, detail="baseline collection failed") from exc

    @app.get("/clients/{client_id}/baselines")
    def client_baselines(client_id: str, context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        store.add_audit_event(
            "baseline.listed",
            client_id,
            "baseline versions listed",
            client_id=client_id,
            approver_id=context.approver_id,
        )
        return [_baseline_view(baseline) for baseline in store.list_client_baselines(scope)]

    @app.post("/clients/{client_id}/baselines/{version}/accept")
    def accept_client_baseline(client_id: str, version: int, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        if active_settings.demo_mode or not active_settings.allow_write_actions:
            raise HTTPException(status_code=403, detail="baseline writes are unavailable in demo mode")
        scope = _resolve_client_target_scope(context, client_id)
        accepted = store.accept_client_baseline(scope, version)
        if accepted is None or accepted.client_id != client_id.strip():
            raise HTTPException(status_code=404, detail="baseline not found")
        return _baseline_view(accepted)

    @app.get("/clients/{client_id}/drift")
    def client_drift(
        client_id: str,
        context: AdminAccess,
        baseline_version: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        if not active_settings.allow_http_probing:
            raise HTTPException(status_code=409, detail="baseline drift requires live read probing")
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            result = baseline_service.diff_baseline(
                client_id,
                baseline_version=baseline_version,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="client baseline not found") from exc
        store.add_audit_event(
            "baseline.drift.viewed",
            client_id,
            "baseline drift comparison completed",
            client_id=client_id,
            approver_id=context.approver_id,
        )
        return result

    @app.get("/clients/{client_id}/graph")
    def client_graph(
        client_id: str,
        context: ViewerAccess,
        entity_type: str | None = None,
        link_type: str | None = None,
        source_system: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict[str, object]:
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            return asdict(
                operational_graph_service.client_graph(
                    scope,
                    entity_type=entity_type,
                    link_type=link_type,
                    source_system=source_system,
                    offset=offset,
                    limit=limit,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/clients/{client_id}/graph/sync-rmm")
    def sync_client_rmm_graph(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            client_rmm_provider = rmm_provider_from_settings(
                active_settings,
                store,
                client_id,
                vault,
            )
        except RmmProviderResolutionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if client_rmm_provider.adapter_id != "local-collector" and not active_settings.allow_http_probing:
            raise HTTPException(status_code=409, detail="RMM read probing is disabled")
        return dict(OperationalGraphService(store, rmm_provider=client_rmm_provider).seed_rmm_inventory(scope))

    @app.post("/clients/{client_id}/graph/sync-m365")
    def sync_client_m365_graph(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        if not active_settings.allow_http_probing:
            raise HTTPException(status_code=409, detail="Microsoft 365 read probing is disabled")
        try:
            service = _m365_graph_service_for_client(client_id)
        except M365ProfileResolutionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return dict(service.seed_m365_inventory(scope))

    @app.patch("/clients/{client_id}")
    def update_client_status(
        client_id: str,
        payload: ClientStatusRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        try:
            client = store.set_client_status(scope, client_id, payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        return asdict(client)

    @app.get("/connector-instances")
    def connector_instances(context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        return [asdict(instance) for instance in store.list_connector_instances()]

    @app.get("/ingestion/sync-cursors")
    def ingestion_sync_cursors(context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        return [asdict(cursor) for cursor in store.list_sync_cursors()]

    @app.get("/ingestion/unmapped")
    def ingestion_unmapped(
        context: ViewerAccess,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        try:
            records = store.list_unmapped_records(
                scope,
                connector_instance_id=connector_instance_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(record) for record in records]

    @app.get("/ingestion/quarantined")
    def ingestion_quarantined(
        context: ViewerAccess,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        normalized_instance_id = _normalize_client_id(connector_instance_id)
        if connector_instance_id is not None and normalized_instance_id is None:
            raise HTTPException(status_code=400, detail="connector_instance_id must be non-empty")
        if isinstance(scope, BoundClients):
            # Quarantine is not a client membership.  Bound viewers must name an
            # instance pinned to one of their ordinary client memberships.
            if normalized_instance_id is None:
                return []
            instance = store.get_connector_instance(normalized_instance_id)
            if (
                instance is None
                or instance.client_id == _QUARANTINE_CLIENT_ID
                or instance.client_id not in scope.client_ids
            ):
                return []
        try:
            tickets = store.list_quarantined_tickets(normalized_instance_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(ticket) for ticket in tickets]

    @app.post("/ingestion/unmapped/{record_id}/resolve")
    def resolve_ingestion_unmapped(record_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        record = store.resolve_unmapped_record(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unmapped record not found")
        return asdict(record)

    @app.post("/ingestion/quarantined/{ticket_id}/reclassify")
    def reclassify_ingestion_quarantined(
        ticket_id: str,
        payload: QuarantineReclassificationRequest,
        context: AdminAccess,
    ) -> dict[str, str]:
        _require_msp_operator(context)
        try:
            store.reclassify_quarantined_ticket(ticket_id, payload.client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ticket_id": ticket_id, "client_id": payload.client_id.strip()}

    @app.post("/connector-instances")
    def create_connector_instance(
        payload: ConnectorInstanceCreateRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        connector_type = payload.connector_type.strip().casefold()
        if not connector_type:
            raise HTTPException(status_code=400, detail="connector_type must be non-empty")
        if connector_type not in SUPPORTED_CONNECTOR_TYPES:
            accepted_types = ", ".join(sorted(SUPPORTED_CONNECTOR_TYPES))
            raise HTTPException(
                status_code=422,
                detail=f"unsupported connector_type; accepted types: {accepted_types}",
            )
        if payload.credential_ref and connector_type in {
            "autotask",
            "syncro",
            "servicenow",
            "ninjaone",
            "dattormm",
            "ncentral",
            "m365",
        }:
            candidate = ConnectorInstance(
                connector_instance_id="pending-validation",
                connector_type=connector_type,
                display_name=payload.display_name,
                client_id=payload.client_id,
                credential_ref=payload.credential_ref,
                config_json=payload.config_json,
                status="inactive",
                created_at="",
                updated_at="",
            )
            try:
                validate_connector_instance(candidate, base_settings=active_settings, vault=vault)
            except ConnectorFactoryError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            instance = store.create_connector_instance(
                payload.connector_type,
                payload.display_name,
                client_id=payload.client_id,
                credential_ref=payload.credential_ref,
                config_json=payload.config_json,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="connector instance already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(instance)

    @app.get("/connector-instances/{connector_instance_id}")
    def connector_instance_detail(
        connector_instance_id: str,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        instance = store.get_connector_instance(connector_instance_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="connector instance not found")
        return asdict(instance)

    @app.patch("/connector-instances/{connector_instance_id}")
    def update_connector_instance(
        connector_instance_id: str,
        payload: ConnectorInstanceUpdateRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        try:
            instance = store.update_connector_instance(
                connector_instance_id,
                **payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="connector instance already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if instance is None:
            raise HTTPException(status_code=404, detail="connector instance not found")
        return asdict(instance)


    @app.get("/client-connector-mappings")
    def client_connector_mappings(
        context: ViewerAccess,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        try:
            mappings = store.list_client_connector_mappings(
                scope,
                connector_instance_id=connector_instance_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(mapping) for mapping in mappings]

    @app.post("/client-connector-mappings")
    def create_client_connector_mapping(
        payload: ClientConnectorMappingCreateRequest,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _resolve_client_target_scope(context, payload.client_id)
        try:
            mapping = store.create_client_connector_mapping(
                scope,
                payload.connector_instance_id,
                payload.external_company_id,
                payload.client_id,
                external_company_name=payload.external_company_name,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            detail = (
                "client not found"
                if str(exc.args[0]) == _normalize_client_id(payload.client_id)
                else "connector instance not found"
            )
            raise HTTPException(status_code=404, detail=detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(mapping)

    @app.post("/client-connector-mappings/{mapping_id}/verify")
    def verify_client_connector_mapping(mapping_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        scope = resolve_client_scope(context, None)
        try:
            verification = store.verify_client_connector_mapping(
                scope,
                mapping_id,
                return_retenanted_count=True,
            )
        except ClientConnectorMappingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except QuarantineRetenantTargetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except QuarantineRetenantStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="mapping not found") from exc
        if not isinstance(verification, tuple):  # pragma: no cover - opt-in route return is always a tuple
            raise RuntimeError("mapping verification did not return re-tenant count")
        mapping, retenanted_count = verification
        response = asdict(mapping)
        response["retenanted_count"] = retenanted_count
        return response

    @app.get("/smart-actions")
    def smart_actions(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(manifest) for manifest in smart_action_service.list()]

    @app.get("/tools")
    def tools(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(tool) for tool in agent_service.list_tools()]

    @app.get("/mcp")
    def mcp_get() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.post("/mcp")
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

    @app.post("/agents/plan")
    def plan_agent(payload: AgentPlanRequest, context: TechnicianAccess) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
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
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            return []
        return [_agent_definition_view(definition) for definition in agent_service.list_definitions(scoped_client_id)]

    @app.post("/agents")
    def create_agent(
        payload: AgentDefinitionRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
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
        scoped_client_id = _resolve_detail_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
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
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
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
        scoped_client_id = _resolve_detail_scope(context, client_id).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
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
        scoped_client_id = resolve_client_scope(context, None).client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
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
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
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
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
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
                correlation_id=_request_correlation_id(request),
            )
        except AgentDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(result)

    def _process_backfill(
        backfill,
        definition,
        context: AuthContext,
        scope: ClientScope,
        scoped_client_id: str | None,
        correlation_id: str | None = None,
    ):
        entity_ids = [item for item in _safe_json_values(backfill.entity_ids_json) if isinstance(item, str)]
        input_payload = _safe_json_object(backfill.input_json)
        run_ids = [
            item
            for item in _safe_json_values(backfill.run_ids_json)
            if isinstance(item, int) and not isinstance(item, bool)
        ]
        failed_entity_ids = [
            item for item in _safe_json_values(backfill.failed_entity_ids_json) if isinstance(item, str)
        ]
        errors = [backfill.error_detail] if backfill.error_detail else []
        if definition.client_id is None and scoped_client_id is not None:
            definition = replace(definition, client_id=scoped_client_id)
        store.update_agent_backfill(
            backfill.id or 0,
            client_id=scope,
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
                    correlation_id=correlation_id,
                )
                if result.status in {"completed", "pending_approval"}:
                    return result, None
                return result, f"{entity_id}: agent run status {result.status}"
            except Exception as exc:  # continue independent entities
                return None, redact_text(f"{entity_id}: {exc}")

        max_concurrency = min(max(1, backfill.max_concurrency), AGENT_BACKFILL_MAX_CONCURRENCY)
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
                    client_id=scope,
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
            client_id=scope,
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
        scoped_client_id = _required_client_id(context, payload.client_id)
        if len(set(payload.entity_ids)) != len(payload.entity_ids):
            raise HTTPException(status_code=422, detail="entity_ids must not contain duplicates")
        definition = agent_service.get(payload.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        backfill_scope = scoped_client_id
        for entity_id in payload.entity_ids:
            if store.get_ticket(entity_id, client_id=backfill_scope) is None:
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
        scoped_client_id = _required_client_id(context, payload.client_id)
        if len(set(payload.entity_ids)) != len(payload.entity_ids):
            raise HTTPException(status_code=422, detail="entity_ids must not contain duplicates")
        definition = agent_service.get(payload.agent_id, scoped_client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        backfill_scope = scoped_client_id
        missing_entity_ids = [
            entity_id
            for entity_id in payload.entity_ids
            if store.get_ticket(entity_id, client_id=backfill_scope) is None
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
        scope = _backfill_scope(context, client_id)
        return [_agent_backfill_view(item) for item in store.list_agent_backfills(scope)]

    @app.get("/agent-backfills/{backfill_id}")
    def agent_backfill_detail(backfill_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        return _agent_backfill_view(backfill)

    @app.post("/agent-backfills/{backfill_id}/run")
    def run_agent_backfill(
        backfill_id: int,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status not in {"queued", "paused"}:
            raise HTTPException(status_code=409, detail="agent backfill is not runnable in its current state")
        definition = agent_service.get(backfill.agent_id, backfill.client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_backfill_view(
            _process_backfill(
                backfill,
                definition,
                context,
                scope,
                backfill.client_id,
                _request_correlation_id(request),
            )
        )

    @app.post("/agent-backfills/{backfill_id}/pause")
    def pause_agent_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status != "queued":
            raise HTTPException(status_code=409, detail="only queued backfills can be paused")
        return _agent_backfill_view(
            store.update_agent_backfill(
                backfill_id,
                client_id=scope,
                status="paused",
                next_index=backfill.next_index,
                processed_count=backfill.processed_count,
                succeeded_count=backfill.succeeded_count,
                failed_count=backfill.failed_count,
                run_ids=[
                    item
                    for item in _safe_json_values(backfill.run_ids_json)
                    if isinstance(item, int) and not isinstance(item, bool)
                ],
                failed_entity_ids=[
                    item for item in _safe_json_values(backfill.failed_entity_ids_json) if isinstance(item, str)
                ],
                error_detail=backfill.error_detail,
            )
        )

    @app.post("/agent-backfills/{backfill_id}/cancel")
    def cancel_agent_backfill(backfill_id: int, context: TechnicianAccess) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        if backfill.status in {"completed", "completed_with_errors", "cancelled"}:
            raise HTTPException(status_code=409, detail="agent backfill is already terminal")
        return _agent_backfill_view(
            store.update_agent_backfill(
                backfill_id,
                client_id=scope,
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
    def rerun_failed_backfill(
        backfill_id: int,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _backfill_scope(context, None)
        backfill = store.get_agent_backfill(backfill_id, scope)
        if backfill is None:
            raise HTTPException(status_code=404, detail="agent backfill not found")
        failed_entity_ids = [
            item for item in _safe_json_values(backfill.failed_entity_ids_json) if isinstance(item, str)
        ]
        if not failed_entity_ids:
            raise HTTPException(status_code=409, detail="agent backfill has no failed entities")
        reset = store.reset_agent_backfill_failed(backfill_id, failed_entity_ids, client_id=scope)
        definition = agent_service.get(reset.agent_id, reset.client_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return _agent_backfill_view(
            _process_backfill(
                reset,
                definition,
                context,
                scope,
                reset.client_id,
                _request_correlation_id(request),
            )
        )

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
    def agent_runs(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [_agent_run_view(run) for run in store.list_agent_runs(scope)]

    @app.get("/agent-runs/{run_id}")
    def agent_run_detail(run_id: int, context: ViewerAccess, client_id: str | None = None) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
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
    def resume_agent(
        run_id: int,
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
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
                correlation_id=_request_correlation_id(request),
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return asdict(result)

    @app.post("/agent-runs/{run_id}/cancel")
    def cancel_agent_run(
        run_id: int,
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
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
                correlation_id=_request_correlation_id(request),
            )
        except (AgentDefinitionError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return asdict(result)

    @app.post("/agent-runs/{run_id}/retry")
    def retry_agent_run(
        run_id: int,
        request: Request,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = store.get_agent_run(run_id, scope)
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
                correlation_id=_request_correlation_id(request),
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

    @app.get("/automation/event-deliveries")
    def event_deliveries(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [_event_delivery_view(delivery) for delivery in store.list_event_deliveries(scope)]

    @app.get("/automation/event-deliveries/{delivery_id}")
    def event_delivery_detail(delivery_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        delivery = store.get_event_delivery(delivery_id, scope)
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

    @app.get("/smart-actions/runs")
    def smart_action_runs(context: ViewerAccess, client_id: str | None = None) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [
            _smart_action_run_view(run)
            for run in smart_action_service.store.list_smart_action_runs(client_id=scope)
        ]

    @app.get("/smart-actions/runs/{run_id}")
    def smart_action_run_detail(run_id: int, context: ViewerAccess, client_id: str | None = None) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        run = smart_action_service.store.get_smart_action_run(run_id, client_id=scope)
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

    @app.post("/technician/chat")
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

    @app.post("/technician/chat/sessions")
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

    @app.get("/technician/chat/sessions")
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

    @app.get("/technician/chat/sessions/{session_id}")
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

    @app.post("/technician/chat/sessions/{session_id}/messages")
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

    @app.post("/technician/chat/sessions/{session_id}/close")
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

    @app.get("/end-user/config", response_model=EndUserBrandingResponse)
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

    @app.post("/end-user/tickets")
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

    @app.get("/end-user/tickets/{ticket_id}")
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

    @app.get("/end-user/tickets/{ticket_id}/messages")
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

    @app.post("/end-user/tickets/{ticket_id}/messages")
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

    @app.get("/tickets/{ticket_id}/end-user-messages")
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

    @app.post("/tickets/{ticket_id}/end-user-messages")
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

    @app.post("/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts")
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

    @app.post("/end-user/tickets/{ticket_id}/escalate")
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

    @app.get("/tickets/{ticket_id}/summary")
    def summarize_ticket(ticket_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        if store.get_ticket(ticket_id, client_id=scope, include_quarantine=False) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        try:
            return asdict(service.summarize(ticket_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc

    @app.get("/tickets/{ticket_id}/context")
    def ticket_context(ticket_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        if store.get_ticket(ticket_id, client_id=scope, include_quarantine=False) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        graph = operational_graph_service.ticket_context(scope, ticket_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        return asdict(graph)

    @app.get("/tickets/{ticket_id}/notes")
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

    @app.get("/tickets/{ticket_id}/status-history")
    def ticket_status_history(ticket_id: str, context: ViewerAccess) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, None).client_id
        if scoped_client_id is None and context.role >= Role.ADMIN:
            ticket = store.get_ticket(ticket_id, include_quarantine=False)
            scoped_client_id = ticket.client_id if ticket is not None else None
        if scoped_client_id is None:
            return []
        return store.list_ticket_status_history(ticket_id, client_id=scoped_client_id)

    @app.post("/tickets/{ticket_id}/approvals")
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

    @app.get("/approval-requests")
    def approval_requests(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [_approval_view(request) for request in store.list_approval_requests(client_id=scope)]

    @app.get("/approval-requests/{request_id}")
    def approval_request_detail(request_id: int, context: ViewerAccess) -> dict[str, object]:
        request = store.get_approval_request(request_id)
        if request is None or not _approval_scope_visible(context, request):
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
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
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
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        try:
            run = collector_service.run(
                module_id,
                payload.config,
                confirm=payload.confirm,
                client_id=scoped_client_id,
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
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                **asdict(run),
                "result_status": collector_run_result_status(run),
                "collection_scope": collector_run_collection_scope(run),
            }
            for run in store.list_collector_runs(
                client_id=resolve_client_scope(context, client_id)
            )
        ]

    @app.get("/collectors/runs/{run_id}")
    def collector_run_detail(run_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        run = store.get_collector_run(run_id, client_id=scope)
        if run is None:
            raise HTTPException(status_code=404, detail="collector run not found")
        return {
            **asdict(run),
            "result_status": collector_run_result_status(run),
            "collection_scope": collector_run_collection_scope(run),
            "assets": [
                asdict(asset)
                for asset in store.list_canonical_assets(run_id=run_id, client_id=scope)
            ],
            "observations": [asdict(observation) for observation in store.list_asset_observations(run_id=run_id)],
            "config_snapshots": [asdict(snapshot) for snapshot in store.list_config_snapshots(run_id=run_id)],
            "config_diffs": [asdict(diff) for diff in store.list_config_diffs(run_id=run_id)],
            "restore_exercises": [asdict(exercise) for exercise in store.list_restore_exercises(run_id=run_id)],
        }

    @app.post("/collectors/runs/{run_id}/export")
    def collector_run_export(
        run_id: int,
        context: ViewerAccess,
        report_type: ReportType = ReportType.COLLECTOR_BUNDLE,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, None)
        if store.get_collector_run(run_id, client_id=scope) is None:
            raise HTTPException(status_code=404, detail="collector run not found")
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
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a client scope")
        scoped_client_id = scope.client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        estimates = {manifest.action_id: manifest.estimated_minutes_saved for manifest in smart_action_service.list()}
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
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a client scope")
        scoped_client_id = scope.client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=400, detail="client_id is required to generate a client report")
        if request.period_end < request.period_start:
            raise HTTPException(status_code=400, detail="period_end must be on or after period_start")
        estimates = {manifest.action_id: manifest.estimated_minutes_saved for manifest in smart_action_service.list()}
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
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a client scope")
        scoped_client_id = scope.client_id
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
        scope = _operator_scope(context, active_settings.client_id, client_id or None)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="reports require a single client or all-client scope")
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=403, detail="reports require a single client or all-client scope")
        scoped_client_id = scope.client_id
        stored = report_service.list_reports(
            report_type=report_type,
            client_id=scoped_client_id or "",
            project_id=project_id,
        )
        return [report_as_dict(report) for report in stored]

    @app.get("/reports/{report_id}")
    def report_detail(report_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=404, detail="report not found")
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="report not found")
        report = report_service.get_report(report_id, client_id=scope.client_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return report_as_dict(report)

    @app.get("/reports/{report_id}/export")
    def report_export(
        report_id: str,
        context: ViewerAccess,
        export_format: Literal["json", "markdown", "pdf"] = "json",
    ) -> Response:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=404, detail="report not found")
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="report not found")
        try:
            rendered = report_service.export_report(
                report_id,
                ReportFormat(export_format),
                client_id=scope.client_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="report not found") from exc
        media_type = {"json": "application/json", "markdown": "text/markdown", "pdf": "application/pdf"}[export_format]
        extension = {"json": "json", "markdown": "md", "pdf": "pdf"}[export_format]
        return Response(
            rendered,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="wait-report-{report_id}.{extension}"'},
        )

    @app.get("/audit")
    def audit(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [asdict(event) for event in store.list_audit_events(client_id=scope)]

    @app.get("/audit-events/export")
    def audit_events_export(
        request: Request,
        context: AdminAccess,
        format: Literal["json", "csv"] = "json",
        from_: Annotated[datetime | None, Query(alias="from")] = None,
        to_: Annotated[datetime | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> Response:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        all_events = store.list_audit_events(client_id=scope)
        filtered = [
            e
            for e in all_events
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
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [asdict(event) for event in store.list_event_history(client_id=scope)]

    mount_flat(app, create_psa_connectors_router(ctx))

    @app.get("/secrets")
    def secrets(_: AdminAccess) -> list[dict[str, object]]:
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="secrets are unavailable in demo mode")
        return [asdict(secret) for secret in list_secret_records(active_settings)]

    @app.post("/secrets")
    def set_secret(payload: SecretSetRequest, _: AdminAccess) -> dict[str, str]:
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="secrets are unavailable in demo mode")
        try:
            SecretVault.initialize(
                active_settings.vault_path,
                demo_mode=active_settings.demo_mode,
            ).set(payload.name, payload.value)
        except (SecretVaultError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"name": payload.name, "status": "stored"}

    @app.get("/backups")
    def list_backups(
        context: AdminAccess,
        page: Annotated[int, Query(ge=1, le=100)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        offset = (page - 1) * page_size
        runs = store.list_backup_runs(limit=page_size, offset=offset)
        backup_schedules = [job for job in store.list_scheduled_jobs() if job.job_kind == "backup"]
        latest_exercise = store.list_restore_exercises()[-1:]
        restore_reference: dict[str, object] | None = None
        if latest_exercise:
            exercise = latest_exercise[0]
            restore_reference = {
                "id": exercise.id,
                "exercise_id": exercise.exercise_id,
                "status": exercise.status,
                "backup_artifact_id": exercise.backup_artifact_id,
                "completed_at": exercise.completed_at,
                "evidence_reference": exercise.exercise_id,
            }
        schedule = _scheduled_job_view(backup_schedules[0]) if backup_schedules else None
        return {
            "items": [asdict(run) for run in runs],
            "runs": [asdict(run) for run in runs],
            "page": page,
            "page_size": page_size,
            "total": store.count_backup_runs(),
            "schedule_configured": schedule is not None,
            "schedule": schedule,
            "last_restore_exercise": restore_reference,
        }

    @app.post("/backups/run")
    def run_backup(context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="backup runs are unavailable in demo mode")
        store.add_audit_event(
            "backup.run_requested",
            "manual",
            "admin requested backup run",
            approver_id=context.approver_id,
        )
        return asdict(scheduler.run_backup())

    @app.post("/backups")
    def create_backup(payload: BackupCreateRequest, _: AdminAccess) -> dict[str, object]:
        try:
            path = backup_state(
                store,
                Path(payload.destination),
                encrypt=payload.encrypt,
                settings=active_settings,
            )
        except (BackupEncryptionError, ValueError) as exc:
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
        except (BackupEncryptionError, ValueError) as exc:
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

    @app.get("/diagnostics/summary")
    def diagnostics_summary(context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        return collect_diagnostics(active_settings, store).to_dict()

    @app.post("/diagnostics/bundle/preview")
    def diagnostics_bundle_preview(
        payload: DiagnosticsBundleRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        return preview_support_bundle(
            active_settings,
            store,
            case_id=payload.case_id,
        ).to_dict()

    @app.post("/diagnostics/bundle")
    def diagnostics_bundle(
        payload: DiagnosticsBundleRequest,
        context: AdminAccess,
    ) -> FileResponse:
        _require_msp_operator(context)
        try:
            result = build_support_bundle(
                active_settings,
                store,
                case_id=payload.case_id,
            )
        except BundleLimitError as exc:
            raise HTTPException(status_code=507, detail="support bundle exceeded its safety limit") from exc
        store.add_audit_event(
            "support.bundle_created",
            result.sha256[:16],
            "redacted support bundle created locally",
        )
        return FileResponse(
            result.path,
            media_type="application/zip",
            filename=result.path.name,
            headers={"X-Support-Bundle-SHA256": result.sha256},
        )

    @app.post("/diagnostics/bundle/upload")
    def diagnostics_bundle_upload(
        payload: DiagnosticsUploadRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        reason = support_upload_refusal(active_settings, consent=payload.consent)
        store.add_audit_event("support.upload_unavailable", "support-bundle", scrub_diagnostic_text(reason))
        raise HTTPException(
            status_code=http_status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "support_upload_unavailable",
                "message": scrub_diagnostic_text(reason),
            },
        )

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


    mount_flat(app, create_documentation_connectors_router(ctx))

    mount_flat(app, create_m365_router(ctx))


    @app.get("/workflows/templates")
    def workflow_templates(_: ViewerAccess) -> list[dict[str, object]]:
        return [asdict(template) for template in list_workflow_templates()]

    @app.get("/msp/playbooks")
    def msp_playbooks(_: ViewerAccess) -> list[dict[str, object]]:
        return [playbook_view(playbook) for playbook in list_msp_playbooks()]

    @app.get("/msp/playbook-entries")
    def msp_playbook_entries(context: ViewerAccess) -> list[dict[str, object]]:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        return [
            msp_playbook_entry_view(entry)
            for entry in store.list_msp_playbook_entries(scope.client_id)
        ]

    @app.post("/msp/playbook-entries", status_code=201)
    def create_msp_playbook_entry_route(
        request: MspPlaybookEntryCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")  # pragma: no cover
        try:
            entry = publish_msp_playbook(
                store,
                request.source_playbook_id,
                provenance=request.provenance,
                definition=request.definition,
                enabled=request.enabled,
                client_id=scoped_client_id,
            )
            return msp_playbook_entry_view(entry)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="source MSP playbook not found") from exc
        except ValueError as exc:  # pragma: no cover
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/msp/playbook-entries/{entry_id}")
    def get_msp_playbook_entry_route(
        entry_id: str,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        entry = store.get_msp_playbook_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found")
        return msp_playbook_entry_view(entry)

    @app.patch("/msp/playbook-entries/{entry_id}")
    def update_msp_playbook_entry_route(
        entry_id: str,
        request: MspPlaybookEntryUpdateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        existing = store.get_msp_playbook_entry(entry_id, scoped_client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found")
        try:
            entry = update_msp_playbook(
                store,
                entry_id,
                client_id=existing.client_id,
                definition=request.definition,
                provenance=request.provenance,
                enabled=request.enabled,
            )
            return msp_playbook_entry_view(entry)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/msp/playbook-entries/{entry_id}/enable")
    def enable_msp_playbook_entry_route(
        entry_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_entry_route(
            entry_id,
            MspPlaybookEntryUpdateRequest(enabled=True),
            context,
        )

    @app.post("/msp/playbook-entries/{entry_id}/disable")
    def disable_msp_playbook_entry_route(
        entry_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_entry_route(
            entry_id,
            MspPlaybookEntryUpdateRequest(enabled=False),
            context,
        )

    @app.get("/msp/playbook-entries/{entry_id}/revisions")
    def list_msp_playbook_revisions_route(
        entry_id: str,
        context: ViewerAccess,
    ) -> list[dict[str, object]]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        if store.get_msp_playbook_entry(entry_id, scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found")
        return [
            msp_playbook_revision_view(revision)
            for revision in store.list_msp_playbook_revisions(entry_id, scoped_client_id)
        ]

    @app.get("/msp/playbook-entries/{entry_id}/revisions/diff")
    def diff_msp_playbook_revisions_route(
        entry_id: str,
        context: ViewerAccess,
        from_version: int = Query(..., ge=1),
        to_version: int = Query(..., ge=1),
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        left = store.get_msp_playbook_revision(entry_id, from_version, scoped_client_id)
        right = store.get_msp_playbook_revision(entry_id, to_version, scoped_client_id)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="MSP playbook revision not found")
        return msp_playbook_revision_diff(left, right)

    @app.post("/msp/playbook-entries/{entry_id}/revisions/{version}/restore")
    def restore_msp_playbook_revision_route(
        entry_id: str,
        version: int,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        existing = store.get_msp_playbook_entry(entry_id, scope.client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="MSP playbook revision not found")
        try:
            return msp_playbook_entry_view(
                store.restore_msp_playbook_revision(entry_id, version, existing.client_id)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook revision not found") from exc
        except ValueError as exc:  # pragma: no cover
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/msp/playbook-subscriptions")
    def msp_playbook_subscriptions(context: ViewerAccess) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        return [
            msp_playbook_subscription_view(subscription)
            for subscription in store.list_msp_playbook_subscriptions(scope)
        ]

    @app.post("/msp/playbook-subscriptions", status_code=201)
    def create_msp_playbook_subscription_route(
        request: MspPlaybookSubscriptionCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, request.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=422, detail="client_id is required for a playbook subscription")
        try:
            subscription = create_msp_playbook_subscription(
                store,
                request.playbook_id,
                event_type=request.event_type,
                client_id=scoped_client_id,
                input_mapping=request.input_mapping,
                enabled=request.enabled,
            )
            return msp_playbook_subscription_view(subscription)
        except (KeyError, PermissionError) as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/msp/playbook-subscriptions/{subscription_id}")
    def get_msp_playbook_subscription_route(
        subscription_id: str,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        subscription = store.get_msp_playbook_subscription(subscription_id, scope)
        if subscription is None:
            raise HTTPException(status_code=404, detail="MSP playbook subscription not found")
        return msp_playbook_subscription_view(subscription)

    @app.patch("/msp/playbook-subscriptions/{subscription_id}")
    def update_msp_playbook_subscription_route(
        subscription_id: str,
        request: MspPlaybookSubscriptionUpdateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        existing = store.get_msp_playbook_subscription(subscription_id, scope)
        if existing is None:
            raise HTTPException(status_code=404, detail="MSP playbook subscription not found")
        scoped_client_id = existing.client_id
        try:
            subscription = update_msp_playbook_subscription(
                store,
                subscription_id,
                client_id=scoped_client_id,
                input_mapping=request.input_mapping,
                enabled=request.enabled,
            )
            return msp_playbook_subscription_view(subscription)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook subscription not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/msp/playbook-subscriptions/{subscription_id}/enable")
    def enable_msp_playbook_subscription_route(
        subscription_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_subscription_route(
            subscription_id,
            MspPlaybookSubscriptionUpdateRequest(enabled=True),
            context,
        )

    @app.post("/msp/playbook-subscriptions/{subscription_id}/disable")
    def disable_msp_playbook_subscription_route(
        subscription_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_subscription_route(
            subscription_id,
            MspPlaybookSubscriptionUpdateRequest(enabled=False),
            context,
        )

    @app.post("/msp/playbooks/{playbook_id}/preview")
    def preview_msp_playbook_route(
        playbook_id: str,
        request: MspPlaybookRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return preview_msp_playbook(
                store,
                playbook_id,
                ticket_id=request.ticket_id,
                client_id=scoped_client_id,
                input_payload=request.payload,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/msp/playbooks/{playbook_id}/runs")
    def run_msp_playbook_route(
        playbook_id: str,
        request: MspPlaybookRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            result = run_msp_playbook(
                store,
                playbook_id,
                ticket_id=request.ticket_id,
                client_id=scoped_client_id,
                actor=context.approver_id or "api",
                trigger_source="msp_playbook_api",
                input_payload=request.payload,
                tool_executor=smart_action_service,
                smart_action_service=smart_action_service,
                on_workflow_run=lambda run: _dispatch_workflow_completion_event(
                    event_dispatcher, run, context.approver_id or "api"
                ),
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/blueprints", status_code=201)
    def create_consultant_blueprint(
        payload: SolutionBlueprintRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        client_id = resolve_client_scope(context, payload.client_id).client_id
        if client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            blueprint = parse_solution_blueprint(
                payload.model_dump(exclude={"client_id"}),
                client_id=client_id,
                created_by=context.approver_id or "api",
            )
            return blueprint_view(store.create_solution_blueprint(blueprint))
        except BlueprintValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/demos/employee-onboarding")
    def run_consultant_employee_onboarding_demo(
        payload: EmployeeOnboardingDemoRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        if not active_settings.demo_mode or active_settings.allow_write_actions:
            raise HTTPException(
                status_code=409,
                detail="employee-onboarding fixture requires local demo mode with writes disabled",
            )
        try:
            scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        except HTTPException as exc:
            if exc.detail == "authenticated principal has no tenant":
                raise HTTPException(
                    status_code=403,
                    detail="employee-onboarding demo requires a tenant scope",
                ) from exc
            raise
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="employee-onboarding demo requires a tenant scope")
        if (payload.blueprint_id is None) == (payload.blueprint is None):
            raise HTTPException(status_code=422, detail="provide exactly one of blueprint_id or blueprint")
        try:
            if payload.blueprint_id is not None:
                persisted = store.get_solution_blueprint(payload.blueprint_id, client_id=scoped_client_id)
                if persisted is None:
                    raise HTTPException(status_code=404, detail="solution blueprint not found in tenant scope")
                blueprint: dict[str, object] = blueprint_payload(persisted)
            else:
                blueprint = cast(dict[str, object], payload.blueprint)
            return run_employee_onboarding_demo(
                store=store,
                settings=active_settings,
                blueprint_payload=blueprint,
                client_id=scoped_client_id,
                entity_id=payload.entity_id,
                blueprint_id=payload.blueprint_id,
                persist_blueprint=payload.blueprint_id is None,
                output_directory=payload.output_directory,
            )
        except EmployeeOnboardingDemoError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/consultant/blueprints")
    def consultant_blueprints(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None and context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        return [blueprint_view(blueprint) for blueprint in store.list_solution_blueprints(client_id=scoped_client_id)]

    @app.get("/consultant/blueprints/{blueprint_id}/architecture")
    def consultant_blueprint_architecture(
        blueprint_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None and context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        blueprint = store.get_solution_blueprint(blueprint_id, client_id=scoped_client_id)
        if blueprint is None:
            raise HTTPException(status_code=404, detail="solution blueprint not found")
        return architect_solution_blueprint(
            blueprint,
            available_tool_ids=(tool.id for tool in agent_service.list_tools()),
            workflow_templates=list_workflow_templates(),
        )

    @app.post("/consultant/blueprints/{blueprint_id}/generate-playbook")
    def generate_consultant_blueprint_playbook(
        blueprint_id: str,
        context: AdminAccess,
        response: Response,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped = resolve_client_scope(context, client_id).client_id
        if scoped is None and context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        blueprint = store.get_solution_blueprint(blueprint_id, client_id=scoped)
        if blueprint is None:
            raise HTTPException(status_code=404, detail="solution blueprint not found")

        architecture = architect_solution_blueprint(
            blueprint,
            available_tool_ids=(tool.id for tool in agent_service.list_tools()),
            workflow_templates=list_workflow_templates(),
        )
        definition = generate_playbook_from_blueprint(blueprint, architecture)
        source_ref = f"architect:{blueprint.id}"
        provenance = f"architect_blueprint:{blueprint.id}"
        entry_id = f"architect-{blueprint.id}"
        existing = store.get_msp_playbook_entry(entry_id, blueprint.client_id)
        if existing is None:
            try:
                entry = store.create_msp_playbook_entry(
                    source_ref,
                    definition,
                    provenance=provenance,
                    client_id=blueprint.client_id,
                    enabled=False,
                    entry_id=entry_id,
                )
                response.status_code = 201
            except sqlite3.IntegrityError:
                entry = store.update_msp_playbook_entry(
                    entry_id,
                    definition=definition,
                    provenance=provenance,
                    enabled=False,
                    client_id=blueprint.client_id,
                    force_revision=True,
                )
        else:
            entry = store.update_msp_playbook_entry(
                entry_id,
                definition=definition,
                provenance=provenance,
                enabled=False,
                client_id=blueprint.client_id,
                force_revision=True,
            )
        return msp_playbook_entry_view(entry)

    @app.post("/consultant/connectors/openapi/validate")
    def validate_consultant_openapi_connector(
        payload: OpenApiConnectorRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            artifact = generate_power_platform_connector(payload.connector_id, payload.definition)
        except OpenApiDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"valid": True, "connector": artifact}

    @app.post("/consultant/connectors/openapi/generate")
    def generate_consultant_openapi_connector(
        payload: OpenApiConnectorRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            return generate_power_platform_connector(payload.connector_id, payload.definition)
        except OpenApiDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/evaluations")
    def evaluate_consultant_contract(
        payload: EvaluationRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            if payload.execution is not None:
                if not active_settings.demo_mode or active_settings.allow_write_actions:
                    raise HTTPException(
                        status_code=409,
                        detail="controlled evaluation execution requires local demo mode with writes disabled",
                    )
                scoped_client_id = resolve_client_scope(context, payload.execution.client_id).client_id
                if scoped_client_id is None:
                    raise HTTPException(status_code=403, detail="evaluation execution requires a tenant scope")
                definition = agent_service.get(payload.execution.agent_id, scoped_client_id)
                if definition is None or definition.client_id != scoped_client_id:
                    raise HTTPException(status_code=404, detail="evaluation agent was not found in tenant scope")
                executor = AgentServiceEvaluationExecutor(
                    agent_service,
                    definition,
                    entity_id=payload.execution.entity_id,
                    actor=context.approver_id or "evaluation",
                    actor_role=context.role,
                    input_payload=payload.execution.input,
                    client_id=scoped_client_id,
                )
                return execute_tool_contract(payload.test_set, executor)
            return evaluate_tool_contract(payload.test_set, payload.observations)
        except EvaluationValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/governance/evaluate")
    def evaluate_consultant_governance(
        payload: GovernanceRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            return evaluate_solution_governance(payload.architecture, payload.connector_artifacts)
        except GovernanceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/power-apps/plan")
    def consultant_power_apps_plan(
        payload: PowerAppsPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_apps_plan(
                client_id=scoped_client_id,
                app_name=payload.app_name,
                entities=payload.entities,
                screens=payload.screens,
                actions=payload.actions,
            )
        except PowerAppsPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/power-apps/build")
    def consultant_power_apps_build(
        payload: PowerAppsPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_apps_artifact(
                client_id=scoped_client_id,
                app_name=payload.app_name,
                entities=payload.entities,
                screens=payload.screens,
                actions=payload.actions,
            )
        except PowerAppsPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/power-platform/package")
    def build_consultant_power_platform_package(
        payload: PowerPlatformPackageRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_platform_package(
                client_id=scoped_client_id,
                solution_name=payload.solution_name,
                publisher_name=payload.publisher_name,
                publisher_prefix=payload.publisher_prefix,
                output_directory=payload.output_directory,
                artifacts=payload.artifacts,
                connector_artifacts=payload.connector_artifacts,
            )
        except PowerPlatformPackageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/consultant/power-platform/cli-status")
    @limiter.limit(active_settings.rate_limit_connector)
    def consultant_power_platform_cli_status(
        request: Request,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        del request
        cli_status = power_platform_cli_status(active_settings)
        version = cli_status.get("version")
        try:
            version_compatible = (
                isinstance(version, str)
                and compare_pac_versions(version, PAC_XML_MINIMUM_VERSION) >= 0
            )
        except ValueError:
            version_compatible = False
        raw_path = cli_status.get("path")
        path_name = None
        if isinstance(raw_path, str) and raw_path:
            path_name = raw_path.replace("\\", "/").rsplit("/", 1)[-1]
        return {
            **cli_status,
            "path": path_name,
            "path_configured": isinstance(raw_path, str) and bool(raw_path),
            "minimum_version": PAC_XML_MINIMUM_VERSION,
            "version_compatible": version_compatible,
            "allow_write_actions": active_settings.allow_write_actions,
            "allow_power_platform_deployment": active_settings.allow_power_platform_deployment,
            "workspace_exists": active_settings.power_platform_workspace.is_dir(),
        }

    @app.post("/consultant/power-platform/package/validate")
    def validate_consultant_power_platform_package(
        payload: PowerPlatformPackageValidationRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        requested = payload.client_id
        package_client = payload.package.get("client_id")
        if requested is None and isinstance(package_client, str):
            requested = package_client
        scoped_client_id = resolve_client_scope(context, requested).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return package_validation_result(payload.package, client_id=scoped_client_id)
        except PowerPlatformPackageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/power-platform/package/materialize")
    def materialize_consultant_power_platform_package(
        payload: PowerPlatformPackageMaterializationRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        if context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="admin access required for package materialization")
        requested = payload.client_id
        package_client = payload.package.get("client_id")
        if requested is None and isinstance(package_client, str):
            requested = package_client
        scoped_client_id = resolve_client_scope(context, requested).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        result = materialize_power_platform_package(
            payload.package,
            active_settings,
            client_id=scoped_client_id,
        )
        if result.get("status") == "failed":
            raise HTTPException(status_code=422, detail=result.get("message", "package materialization failed"))
        return result

    def _consultant_discovery_result(client_id: str, answers: dict[str, object]) -> dict[str, object]:
        preliminary = build_solution_discovery(client_id=client_id, answers=answers)
        environment = discover_solution_environment(
            client_id=client_id,
            systems=cast(list[object], preliminary["answered"].get("systems", [])),
            connector_statuses=list_connector_statuses(active_settings),
            configured_client_id=active_settings.client_id,
        )
        return build_solution_discovery(client_id=client_id, answers=answers, environment=environment)

    def _promote_completed_discovery(
        result: dict[str, object],
        *,
        client_id: str,
        created_by: str,
    ) -> dict[str, object]:
        """Persist complete guided evidence as a review-only blueprint."""

        if result.get("status") != "complete":
            return result
        candidate = result.get("blueprint_candidate")
        answered = result.get("answered")
        if not isinstance(candidate, dict) or not isinstance(answered, dict):
            raise DiscoveryValidationError("completed discovery is missing blueprint evidence")
        solution = candidate.get("solution")
        solution_name = solution.get("name") if isinstance(solution, dict) else None
        if not isinstance(solution_name, str) or not solution_name.strip():
            solution_name = "Guided discovery solution"
        risk_review = result.get("risk_review")
        risk = risk_review.get("level") if isinstance(risk_review, dict) else None
        if risk not in {"low", "medium", "high"}:
            risk = "high" if answered.get("data_leaves_tenant") is True else "medium"
        try:
            blueprint = promote_discovery_candidate(
                candidate,
                client_id=client_id,
                solution_name=solution_name.strip(),
                risk=cast(str, risk),
                created_by=created_by,
            )
            persisted = store.create_solution_blueprint(blueprint)
        except BlueprintValidationError as exc:
            raise DiscoveryValidationError(f"completed discovery cannot become a blueprint: {exc}") from exc
        result["blueprint_id"] = persisted.id
        result["blueprint"] = blueprint_view(persisted)
        return result

    def _consultant_discovery_session_view(
        session: ConsultantDiscoverySession,
        *,
        client_id: str,
    ) -> dict[str, object]:
        """Rehydrate one persisted session without adding inference or execution."""

        try:
            answers_value = json.loads(session.answers_json)
            transcript_value = json.loads(session.transcript_json)
        except json.JSONDecodeError as exc:
            raise DiscoveryValidationError("discovery session state is invalid") from exc
        if not isinstance(answers_value, dict) or not isinstance(transcript_value, list):
            raise DiscoveryValidationError("discovery session state is invalid")
        transcript = [item for item in transcript_value if isinstance(item, dict)]
        result = _consultant_discovery_result(client_id, cast(dict[str, object], answers_value))
        result["session_status"] = session.status
        result["session_id"] = session.id
        result["principal_scope"] = session.principal_id
        result["transcript"] = transcript
        result["turn_index"] = max(0, (len(transcript) - 1) // 2)
        result["blueprint_id"] = session.blueprint_id
        result["created_at"] = session.created_at
        result["updated_at"] = session.updated_at
        return result

    @app.post("/consultant/discovery")
    def consultant_discovery(
        payload: DiscoveryRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return _consultant_discovery_result(scoped_client_id, payload.answers)
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/discovery/promote", status_code=201)
    def consultant_discovery_promote(
        payload: DiscoveryBlueprintPromotionRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            discovery = _consultant_discovery_result(scoped_client_id, payload.answers)
            missing = cast(list[object], discovery["missing_required"])
            if missing:
                fields = ", ".join(str(item) for item in missing)
                raise DiscoveryValidationError(f"discovery is missing required answers: {fields}")
            candidate = discovery.get("blueprint_candidate")
            if not isinstance(candidate, dict):
                raise DiscoveryValidationError("discovery blueprint candidate is invalid")
            blueprint = promote_discovery_candidate(
                candidate,
                client_id=scoped_client_id,
                solution_name=payload.solution_name,
                risk=payload.risk,
                created_by=context.approver_id or "api",
            )
            persisted = store.create_solution_blueprint(blueprint)
            return {
                "blueprint": blueprint_view(persisted),
                "discovery": discovery,
                "execution_started": False,
                "deployment_started": False,
            }
        except (BlueprintValidationError, DiscoveryValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/discovery/sessions")
    def consultant_discovery_session_start(
        payload: DiscoverySessionStartRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        answers = dict(payload.answers)
        opening_message = payload.opening_message.strip() if payload.opening_message else None
        try:
            if opening_message:
                build_solution_discovery(
                    client_id=scoped_client_id,
                    answers={"business_goal": opening_message},
                )
                if "business_goal" not in answers:
                    answers["business_goal"] = opening_message
            result = _promote_completed_discovery(
                _consultant_discovery_result(scoped_client_id, answers),
                client_id=scoped_client_id,
                created_by=context.approver_id or "api",
            )
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        principal_id = context.approver_id or "api"
        answered = cast(dict[str, object], result["answered"])
        transcript: list[dict[str, object]] = []
        if opening_message:
            transcript.append(
                {
                    "role": "user",
                    "field": "business_goal",
                    "content": answered.get("business_goal", opening_message),
                }
            )
        next_question = cast(dict[str, object] | None, result.get("next_question"))
        if next_question is not None:
            transcript.append(
                {
                    "role": "assistant",
                    "field": next_question["id"],
                    "content": next_question["prompt"],
                }
            )
        session = store.create_consultant_discovery_session(
            client_id=scoped_client_id,
            principal_id=principal_id,
            answers=answered,
            transcript=transcript,
            blueprint_id=cast(str | None, result.get("blueprint_id")),
        )
        return _consultant_discovery_session_view(session, client_id=scoped_client_id)

    @app.get("/consultant/discovery/sessions")
    def consultant_discovery_session_list(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = context.approver_id or "api"
        try:
            sessions = store.list_consultant_discovery_sessions(
                client_id=scoped_client_id,
                principal_id=principal_id,
            )
            return [
                _consultant_discovery_session_view(session, client_id=scoped_client_id)
                for session in sessions
            ]
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/consultant/discovery/sessions/{session_id}")
    def consultant_discovery_session_get(
        session_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = context.approver_id or "api"
        session = store.get_consultant_discovery_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="discovery session not found")
        try:
            return _consultant_discovery_session_view(session, client_id=scoped_client_id)
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/consultant/discovery/sessions/{session_id}/turn")
    def consultant_discovery_session_turn(
        session_id: str,
        payload: DiscoveryTurnRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = context.approver_id or "api"
        session = store.get_consultant_discovery_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="discovery session not found")
        if session.status != "active":
            raise HTTPException(status_code=409, detail="discovery session is already complete")
        if payload.field == "impact":
            raise HTTPException(status_code=422, detail="impact estimates belong to stateless discovery intake")
        try:
            answers_value = json.loads(session.answers_json)
            transcript_value = json.loads(session.transcript_json)
            if not isinstance(answers_value, dict) or not isinstance(transcript_value, list):
                raise DiscoveryValidationError("discovery session state is invalid")
            answers = dict(cast(dict[str, object], answers_value))
            answers[payload.field] = payload.answer
            result = _promote_completed_discovery(
                _consultant_discovery_result(scoped_client_id, answers),
                client_id=scoped_client_id,
                created_by=principal_id,
            )
        except (DiscoveryValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        answered = cast(dict[str, object], result["answered"])
        transcript = [item for item in cast(list[object], transcript_value) if isinstance(item, dict)]
        transcript.append(
            {
                "role": "user",
                "field": payload.field,
                "content": answered[payload.field],
            }
        )
        next_question = cast(dict[str, object] | None, result.get("next_question"))
        if next_question is not None:
            transcript.append(
                {
                    "role": "assistant",
                    "field": next_question["id"],
                    "content": next_question["prompt"],
                }
            )
        if len(transcript) > 64:
            raise HTTPException(status_code=422, detail="discovery session has reached its turn limit")
        discovery_status = cast(str, result["status"])
        persisted_status = {
            "active": "active",
            "complete": "completed",
        }.get(discovery_status)
        if persisted_status is None:
            raise HTTPException(status_code=422, detail="discovery result status is invalid")
        updated = store.update_consultant_discovery_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
            status=persisted_status,
            answers=answered,
            transcript=transcript,
            blueprint_id=cast(str | None, result.get("blueprint_id")),
        )
        if updated is None:
            raise HTTPException(status_code=409, detail="discovery session could not be updated")
        return _consultant_discovery_session_view(updated, client_id=scoped_client_id)

    @app.post("/consultant/environment-discovery")
    def consultant_environment_discovery(
        payload: EnvironmentDiscoveryRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            connector_statuses = list_connector_statuses(active_settings)
            result = discover_solution_environment(
                client_id=scoped_client_id,
                systems=payload.systems,
                connector_statuses=connector_statuses,
                configured_client_id=active_settings.client_id,
            )
            if payload.probe:
                connector_ids = [
                    cast(str, item["connector_id"])
                    for item in cast(list[dict[str, object]], result["systems"])
                    if isinstance(item.get("connector_id"), str)
                    and item.get("status") == "configured"
                ]
                probe_results = (
                    probe_connector_health(
                        connector_ids,
                        active_settings,
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
                        m365_client=m365_client,
                        timezest_client=timezest_client,
                        scalepad_client=scalepad_client,
                    )
                    if active_settings.allow_http_probing
                    else {}
                )
                result = discover_solution_environment(
                    client_id=scoped_client_id,
                    systems=payload.systems,
                    connector_statuses=connector_statuses,
                    configured_client_id=active_settings.client_id,
                    probe_results=probe_results,
                )
            status_counts: dict[str, int] = {}
            for item in cast(list[dict[str, object]], result["systems"]):
                status = item.get("status")
                if isinstance(status, str):
                    status_counts[status] = status_counts.get(status, 0) + 1
            store.add_audit_event(
                "consultant.environment_discovery",
                scoped_client_id,
                f"probe_requested={payload.probe} probe_performed={result['probe_performed']} "
                f"system_statuses={json.dumps(status_counts, sort_keys=True)}",
                client_id=scoped_client_id,
                approver_id=context.approver_id or "api",
            )
            return result
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/supervisor/plan")
    def consultant_supervisor_plan(
        payload: SupervisorPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        definitions = agent_service.list_definitions(scoped_client_id)
        try:
            return build_supervisor_delegation_plan(
                client_id=scoped_client_id,
                task=payload.task,
                child_agent_ids=payload.child_agent_ids,
                definitions=definitions,
                max_retries=payload.max_retries,
            )
        except SupervisorPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/supervisor/run")
    def consultant_supervisor_run(
        payload: SupervisorRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        definitions = agent_service.list_definitions(scoped_client_id)
        try:
            return execute_supervisor_delegation(
                client_id=scoped_client_id,
                entity_id=payload.entity_id,
                task=payload.task,
                child_agent_ids=payload.child_agent_ids,
                definitions=definitions,
                agent_service=agent_service,
                store=store,
                actor=context.approver_id or "api",
                actor_role=context.role,
                input_payload=payload.input,
                completed_run_ids=payload.completed_run_ids,
                max_retries=payload.max_retries,
                cancel_run_id=payload.cancel_run_id,
            )
        except SupervisorPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/delivery-plan")
    def consultant_delivery_plan(
        payload: DeliveryPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_consultant_delivery_plan(
                client_id=scoped_client_id,
                architecture=payload.architecture,
                evaluation=payload.evaluation,
                governance=payload.governance,
                deployment_targets=payload.deployment_targets,
                connector_artifacts=payload.connector_artifacts,
                review_artifacts=payload.review_artifacts,
                deployable_package=payload.deployable_package,
            )
        except DeliveryPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/solutions/deployment-approvals", status_code=201)
    @limiter.limit(active_settings.rate_limit_connector)
    def request_power_platform_deployment_approval(
        payload: PowerPlatformDeploymentRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            plan = build_power_platform_deployment_plan(
                solution_name=payload.solution_name,
                publisher_name=payload.publisher_name,
                publisher_prefix=payload.publisher_prefix,
                output_directory=payload.output_directory,
                deployment_targets=payload.deployment_targets,
            )
            promotion_evidence = validate_promotion_evidence(payload.stage, payload.promotion_evidence)
            approval_payload = {
                "format": "wait-local-agent.power-platform.deployment-approval",
                "format_version": 1,
                "client_id": scoped_client_id,
                "solution_name": payload.solution_name,
                "publisher_name": payload.publisher_name,
                "publisher_prefix": payload.publisher_prefix,
                "output_directory": payload.output_directory,
                "deployment_targets": plan["deployment_targets"],
                "stage": payload.stage,
                "promotion_evidence": promotion_evidence,
                "credentials_included": False,
            }
            if promotion_evidence:
                source_id = cast(int, promotion_evidence["source_approval_request_id"])
                source_approval = store.get_approval_request(source_id)
                if source_approval is not None and not _approval_scope_visible(context, source_approval):
                    source_approval = None
                validate_promotion_source(
                    payload.stage,
                    promotion_evidence,
                    source_approval=_power_platform_source_record(source_approval),
                    current_payload=approval_payload,
                )
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        approval = store.create_approval_request(
            subject_id=f"{scoped_client_id}:{payload.solution_name}:{payload.stage}",
            action_type="power_platform.solution_stage",
            payload=approval_payload,
            client_id=scoped_client_id,
        )
        return {"approval": _approval_view(approval), "plan": plan}

    @app.post("/consultant/solutions/deployment-approvals/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_power_platform_deployment_stage(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        approval = store.get_approval_request(request_id)
        if (
            approval is None
            or approval.action_type != "power_platform.solution_stage"
            or not _approval_scope_visible(context, approval)
        ):
            raise HTTPException(status_code=404, detail="deployment approval request not found")
        if approval.status != "approved":
            raise HTTPException(status_code=409, detail="deployment approval must be approved before execution")
        if approval.execution_status in _TERMINAL_EXECUTION_STATUSES:
            raise HTTPException(status_code=409, detail="deployment approval request has already executed")
        try:
            payload = _safe_json_object(approval.payload_json)
            plan = build_power_platform_deployment_plan_from_payload(payload)
            stage_id = payload.get("stage")
            if not isinstance(stage_id, str):
                raise PowerPlatformDeploymentError("deployment approval stage is invalid")
            promotion_evidence = payload.get("promotion_evidence")
            if isinstance(promotion_evidence, dict) and promotion_evidence:
                source_id = promotion_evidence.get("source_approval_request_id")
                if not isinstance(source_id, int) or isinstance(source_id, bool):
                    raise PowerPlatformDeploymentError("promotion evidence source approval id is invalid")
                source_approval = store.get_approval_request(source_id)
                if source_approval is not None and not _approval_scope_visible(context, source_approval):
                    source_approval = None
                validate_promotion_source(
                    stage_id,
                    promotion_evidence,
                    source_approval=_power_platform_source_record(source_approval),
                    current_payload=payload,
                )
            if not store.claim_approval_execution(request_id):
                raise HTTPException(status_code=409, detail="deployment approval request has already executed")
            result = execute_power_platform_stage(
                plan,
                stage_id,
                active_settings,
                approved=True,
            )
            updated = store.record_approval_execution(
                request_id,
                status=cast(str, result["status"]),
                message=cast(str, result["message"]),
                result=result,
                audit_event_type="power_platform.solution_stage",
            )
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (KeyError, PermissionError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _approval_view(updated)

    @app.post("/consultant/solutions/rollback-approvals", status_code=201)
    @limiter.limit(active_settings.rate_limit_connector)
    def request_power_platform_rollback_approval(
        payload: PowerPlatformRollbackRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        del request
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            plan = build_power_platform_deployment_plan(
                solution_name=payload.solution_name,
                publisher_name=payload.publisher_name,
                publisher_prefix=payload.publisher_prefix,
                output_directory=payload.output_directory,
                deployment_targets=payload.deployment_targets,
            )
            rollback_evidence = validate_rollback_evidence(payload.rollback_evidence)
            artifact_digest = validate_power_platform_solution_package(
                Path(payload.rollback_artifact_path),
                active_settings.power_platform_workspace,
            )
            if artifact_digest != rollback_evidence["artifact_digest"]:
                raise PowerPlatformDeploymentError(
                    "rollback artifact digest does not match rollback evidence"
                )
            approval_payload = {
                "format": "wait-local-agent.power-platform.rollback-approval",
                "format_version": 1,
                "client_id": scoped_client_id,
                "solution_name": payload.solution_name,
                "publisher_name": payload.publisher_name,
                "publisher_prefix": payload.publisher_prefix,
                "output_directory": payload.output_directory,
                "deployment_targets": plan["deployment_targets"],
                "stage": payload.stage,
                "rollback_artifact_path": str(Path(payload.rollback_artifact_path).expanduser().resolve()),
                "rollback_evidence": rollback_evidence,
                "credentials_included": False,
            }
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        approval = store.create_approval_request(
            subject_id=f"{scoped_client_id}:{payload.solution_name}:rollback:{payload.stage}",
            action_type="power_platform.solution_rollback",
            payload=approval_payload,
            client_id=scoped_client_id,
        )
        return {"approval": _approval_view(approval), "plan": plan}

    @app.post("/consultant/solutions/rollback-approvals/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_power_platform_rollback_approval(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        del request
        approval = store.get_approval_request(request_id)
        if (
            approval is None
            or approval.action_type != "power_platform.solution_rollback"
            or not _approval_scope_visible(context, approval)
        ):
            raise HTTPException(status_code=404, detail="Power Platform rollback approval request not found")
        if approval.status != "approved":
            raise HTTPException(status_code=409, detail="rollback approval must be approved before execution")
        if approval.execution_status in _TERMINAL_EXECUTION_STATUSES:
            raise HTTPException(status_code=409, detail="rollback approval request has already executed")
        try:
            payload = _safe_json_object(approval.payload_json)
            plan = build_power_platform_deployment_plan_from_payload(payload)
            stage_id = payload.get("stage")
            artifact_path = payload.get("rollback_artifact_path")
            rollback_evidence = payload.get("rollback_evidence")
            if not isinstance(stage_id, str):
                raise PowerPlatformDeploymentError("rollback approval stage is invalid")
            if not isinstance(artifact_path, str):
                raise PowerPlatformDeploymentError("rollback approval artifact path is invalid")
            normalized_evidence = validate_rollback_evidence(rollback_evidence)
            if not store.claim_approval_execution(request_id):
                raise HTTPException(status_code=409, detail="rollback approval request has already executed")
            result = execute_power_platform_rollback(
                plan,
                stage_id,
                active_settings,
                rollback_artifact_path=artifact_path,
                rollback_evidence=normalized_evidence,
                approved=True,
            )
            updated = store.record_approval_execution(
                request_id,
                status=cast(str, result["status"]),
                message=cast(str, result["message"]),
                result=result,
                audit_event_type="power_platform.solution_rollback",
            )
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (KeyError, PermissionError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _approval_view(updated)

    @app.get("/consultant/use-cases")
    def consultant_use_cases(
        context: ViewerAccess,
        category: str | None = Query(default=None, max_length=32),
    ) -> dict[str, object]:
        del context
        try:
            return list_consultant_use_cases(category)
        except UseCaseCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/workflows/power-automate/plan")
    def consultant_power_automate_plan(
        payload: PowerAutomatePlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_automate_flow_plan(
                client_id=scoped_client_id,
                workflow_id=payload.workflow_id,
                workflow_name=payload.workflow_name,
                trigger=payload.trigger,
                steps=payload.steps,
            )
        except PowerAutomatePlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/consultant/copilot-studio/plan")
    def consultant_copilot_studio_plan(
        payload: CopilotStudioPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_copilot_studio_plan(
                client_id=scoped_client_id,
                copilot_name=payload.copilot_name,
                business_goal=payload.business_goal,
                topics=payload.topics,
                knowledge_sources=payload.knowledge_sources,
                actions=payload.actions,
            )
        except CopilotStudioPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/consultant/monitoring/agents")
    def consultant_agent_monitoring(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, client_id)
        scoped_client_id = scope.client_id
        return build_agent_health_summary(
            store.list_agent_runs(scope),
            agent_service.list_definitions(scoped_client_id),
            client_id=scoped_client_id,
        )

    @app.get("/consultant/blueprints/{blueprint_id}")
    def consultant_blueprint_detail(
        blueprint_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _resolve_detail_scope(context, client_id).client_id
        if scoped_client_id is None and context.role < Role.ADMIN and not context.is_msp_admin:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        blueprint = store.get_solution_blueprint(blueprint_id, client_id=scoped_client_id)
        if blueprint is None:
            raise HTTPException(status_code=404, detail="solution blueprint not found")
        return blueprint_view(blueprint)

    @app.get("/workflow-templates/gallery")
    def template_gallery(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [_template_gallery_view(entry) for entry in store.list_template_gallery_entries(scope)]

    @app.post("/workflow-templates/gallery")
    def create_template_gallery_entry(
        payload: TemplateGalleryCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        template = get_workflow_template(payload.source_template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        scoped_client_id = _required_client_id(context, payload.client_id)
        try:
            definition = payload.definition if payload.definition is not None else default_workflow_design(template)
            entry = store.create_template_gallery_entry(
                template,
                provenance=payload.provenance,
                client_id=scoped_client_id,
                name=payload.display_name,
                instructions=payload.instructions,
                definition=definition,
            )
        except (ValueError, WorkflowDesignError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(entry)

    @app.get("/workflow-templates/gallery/{entry_id}/export")
    def export_template_gallery_entry(entry_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        return _template_gallery_export_view(entry)

    @app.post("/workflow-templates/gallery/import")
    def import_template_gallery_entry(
        payload: TemplateGalleryImportRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        template = get_workflow_template(payload.source_template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        scoped_client_id = _required_client_id(context, payload.client_id)
        try:
            entry = store.create_template_gallery_entry(
                template,
                provenance=payload.provenance,
                client_id=scoped_client_id,
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                enabled=False,
                definition=(
                    payload.definition if payload.definition is not None else default_workflow_design(template)
                ),
            )
        except (ValueError, WorkflowDesignError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(entry)

    @app.get("/workflow-templates/gallery/{entry_id}")
    def template_gallery_detail(entry_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        return _template_gallery_view(entry)

    @app.patch("/workflow-templates/gallery/{entry_id}")
    def update_template_gallery_entry(
        entry_id: str,
        payload: TemplateGalleryUpdateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, payload.client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        try:
            updated = store.update_template_gallery_entry(
                entry_id,
                name=payload.name,
                description=payload.description,
                instructions=payload.instructions,
                enabled=payload.enabled,
                definition=payload.definition,
                client_id=entry.client_id,
            )
        except (ValueError, WorkflowDesignError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _template_gallery_view(updated)

    @app.get("/workflow-templates/gallery/{entry_id}/revisions")
    def template_gallery_revisions(
        entry_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            return []
        return [
            _template_gallery_revision_view(revision)
            for revision in store.list_template_gallery_revisions(
                entry_id,
                entry.client_id if entry.client_id is not None else AllClients(),
            )
        ]

    @app.get("/workflow-templates/gallery/{entry_id}/revisions/{version}/diff/{other_version}")
    def template_gallery_revision_diff(
        entry_id: str,
        version: int,
        other_version: int,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery revision not found")
        revision_scope = entry.client_id if entry.client_id is not None else AllClients()
        left = store.get_template_gallery_revision(entry_id, version, revision_scope)
        right = store.get_template_gallery_revision(entry_id, other_version, revision_scope)
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
        scope = _resolve_detail_scope(context, payload.client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        try:
            restored = store.restore_template_gallery_revision(
                entry_id,
                version,
                entry.client_id if entry.client_id is not None else AllClients(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="template gallery revision not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="template gallery revision is no longer valid") from exc
        return _template_gallery_view(restored)

    @app.post("/workflow-templates/gallery/{entry_id}/runs")
    def run_template_gallery_entry(
        entry_id: str,
        payload: WorkflowRunRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, payload.client_id)
        entry = store.get_template_gallery_entry(entry_id, scope)
        if entry is None:
            raise HTTPException(status_code=404, detail="template gallery entry not found")
        if not entry.enabled:
            raise HTTPException(status_code=409, detail="template gallery entry is disabled")
        ticket = store.get_ticket(payload.ticket_id, client_id=scope)
        if ticket is None or ticket.client_id != entry.client_id:
            raise HTTPException(status_code=404, detail="ticket not found")
        source_template = get_workflow_template(entry.source_template_id)
        if source_template is None:
            raise HTTPException(status_code=409, detail="source workflow template is unavailable")
        try:
            run = run_workflow_template(
                store,
                entry.source_template_id,
                payload.ticket_id,
                client_id=entry.client_id,
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
                input_payload=payload.payload,
                correlation_id=_request_correlation_id(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if run.id is None:
            raise HTTPException(status_code=409, detail="ticket is quarantined pending client mapping")
        _dispatch_workflow_completion_event(event_dispatcher, run, context.approver_id or "api")
        return asdict(run)

    @app.get("/scheduled-jobs")
    def scheduled_jobs(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [_scheduled_job_view(job) for job in scheduler.list_jobs(client_id=scope)]

    @app.post("/scheduled-jobs")
    def create_scheduled_job(
        request: ScheduledJobCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        if request.job_kind == "backup":
            return _create_scheduled_backup_job(request, context)
        if request.job_kind == "baseline_snapshot":
            return _create_scheduled_baseline_snapshot_job(request, context)
        if request.graph_sync or request.job_kind == "graph_sync":
            return _create_scheduled_graph_sync_job(request, context)
        if request.playbook_id is not None:
            return _create_scheduled_playbook_job(request, context)
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
        normalized_requested_client_id = (
            requested_client_id.strip() if isinstance(requested_client_id, str) else None
        )
        scope = resolve_client_scope(context, normalized_requested_client_id)
        ticket = store.get_ticket(ticket_id, client_id=scope)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        params = dict(request.params)
        if ticket.client_id:
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

    def _create_scheduled_backup_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="administrator access required")
        _require_msp_operator(context)
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="backup scheduling is unavailable in demo mode")
        if request.graph_sync or any(
            value is not None
            for value in (
                request.template_id,
                request.report_type,
                request.playbook_id,
                request.agent_id,
                request.entity_id,
            )
        ):
            raise HTTPException(status_code=422, detail="backup schedules cannot include another target")
        if request.params:
            raise HTTPException(status_code=422, detail="backup schedules do not accept params")
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                {},
                job_kind="backup",
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_playbook_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if request.template_id is not None or request.report_type is not None or request.agent_id is not None:
            raise HTTPException(status_code=422, detail="playbook schedules cannot include another target")
        if request.entity_id is not None:
            raise HTTPException(status_code=422, detail="playbook schedules use params.ticket_id")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = _required_client_id(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        )
        raw_ticket_id = request.params.get("ticket_id")
        if raw_ticket_id is not None and not isinstance(raw_ticket_id, str):
            raise HTTPException(status_code=422, detail="params.ticket_id must be a string")
        raw_input = request.params.get("input", {})
        if not isinstance(raw_input, dict):
            raise HTTPException(status_code=422, detail="params.input must be an object")
        try:
            preview = preview_msp_playbook(
                store,
                request.playbook_id or "",
                ticket_id=raw_ticket_id.strip() if isinstance(raw_ticket_id, str) and raw_ticket_id.strip() else None,
                client_id=scoped_client_id,
                input_payload=raw_input,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        effective_client_id = preview.get("client_id")
        if not isinstance(effective_client_id, str) or not effective_client_id:
            raise HTTPException(status_code=422, detail="scheduled playbook requires a client scope")
        params = dict(request.params)
        params["client_id"] = effective_client_id
        if isinstance(raw_ticket_id, str) and raw_ticket_id.strip():
            params["ticket_id"] = raw_ticket_id.strip()
        params["input"] = dict(raw_input)
        try:
            scheduled_job = scheduler.register(
                request.playbook_id or "",
                request.cron,
                params,
                job_kind="playbook",
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
        scoped_client_id = resolve_client_scope(context, requested_client_id).client_id
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
        scope = resolve_client_scope(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        )
        scoped_client_id = scope.client_id
        if scoped_client_id is None:
            scoped_client_id = _normalize_client_id(context.client_id)
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="client scope is required")
        definition = agent_service.get(request.agent_id or "")
        if definition is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if definition.trigger != "scheduled":
            raise HTTPException(status_code=422, detail="agent is not configured for scheduled execution")
        if definition.client_id is not None and definition.client_id != scoped_client_id:
            raise HTTPException(status_code=404, detail="agent not found")
        effective_client_id = definition.client_id or scoped_client_id
        ticket_scope = effective_client_id if effective_client_id is not None else scope
        ticket = store.get_ticket(request.entity_id, client_id=ticket_scope)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        params = dict(request.params)
        raw_client_id = params.get("client_id")
        if (
            raw_client_id is None or (isinstance(raw_client_id, str) and not raw_client_id.strip())
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

    def _create_scheduled_graph_sync_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if any(
            value is not None
            for value in (request.template_id, request.report_type, request.playbook_id, request.agent_id)
        ):
            raise HTTPException(status_code=422, detail="environment sync schedules cannot include another target")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = resolve_client_scope(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        ).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="client scope is required")
        if store.get_client(AllClients(), scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        params = dict(request.params)
        params["client_id"] = scoped_client_id
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                params,
                job_kind="graph_sync",
                entity_id=scoped_client_id,
                schedule_type=request.schedule_type,
                interval_seconds=request.interval_seconds,
                run_at=request.run_at,
                timezone=request.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _scheduled_job_view(scheduled_job)

    def _create_scheduled_baseline_snapshot_job(
        request: ScheduledJobCreateRequest,
        context: AuthContext,
    ) -> dict[str, object]:
        if context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="administrator access required")
        _require_msp_operator(context)
        if active_settings.demo_mode or not active_settings.allow_write_actions:
            raise HTTPException(status_code=403, detail="baseline scheduling is unavailable in demo mode")
        if any(
            value is not None
            for value in (request.template_id, request.report_type, request.playbook_id, request.agent_id)
        ):
            raise HTTPException(status_code=422, detail="baseline snapshot schedules cannot include another target")
        requested_client_id = request.params.get("client_id")
        if requested_client_id is not None and not isinstance(requested_client_id, str):
            raise HTTPException(status_code=422, detail="params.client_id must be a string")
        scoped_client_id = resolve_client_scope(
            context,
            requested_client_id.strip() if isinstance(requested_client_id, str) else None,
        ).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="client scope is required")
        if store.get_client(AllClients(), scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        params = dict(request.params)
        params["client_id"] = scoped_client_id
        try:
            scheduled_job = scheduler.register(
                "",
                request.cron,
                params,
                job_kind="baseline_snapshot",
                entity_id=scoped_client_id,
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
        payload: WorkflowRunRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, payload.client_id)
        ticket = store.get_ticket(payload.ticket_id, client_id=scope)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        try:
            run = run_workflow_template(
                store,
                template_id,
                payload.ticket_id,
                client_id=ticket.client_id,
                actor=context.approver_id or "api",
                trigger_source="api",
                tool_executor=smart_action_service,
                input_payload=payload.payload,
                correlation_id=_request_correlation_id(request),
            )
            if run.id is None:
                raise HTTPException(status_code=409, detail="ticket is quarantined pending client mapping")
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
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        return [asdict(run) for run in store.list_workflow_runs(client_id=scope)]

    @app.get("/workflow-runs/{run_id}")
    def workflow_run_detail(run_id: int, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        run = store.get_workflow_run(run_id, client_id=scope)
        if run is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        template = next(
            (item for item in list_workflow_templates() if item.id == run.template_id),
            None,
        )
        approval = store.get_approval_request(run.approval_request_id) if run.approval_request_id is not None else None
        return {
            **asdict(run),
            "template": asdict(template) if template is not None else None,
            "approval_request": (
                _approval_view(approval)
                if (
                    approval is not None
                    and approval.client_id == run.client_id
                    and _approval_scope_visible(context, approval)
                )
                else None
            ),
            "events": [asdict(event) for event in store.list_event_history_for_subject(run.ticket_id)],
        }

    @app.get("/workflow-runs/{run_id}/compare/{other_run_id}")
    def workflow_run_compare(
        run_id: int,
        other_run_id: int,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        left = store.get_workflow_run(run_id, client_id=scope)
        right = store.get_workflow_run(other_run_id, client_id=scope)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return _workflow_run_comparison_view(left, right)

    @app.get("/executions")
    def executions(
        request: Request,
        context: ViewerAccess,
        kind: str | None = None,
        status: str | None = None,
        started_from: Annotated[str | None, Query(alias="from")] = None,
        started_to: Annotated[str | None, Query(alias="to")] = None,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, requested_client_from(request, client_id))
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=403, detail="execution lists require a single client or all-client scope")
        return [
            _execution_run_view(run)
            for run in store.list_execution_runs(
                client_id=scope,
                run_kind=kind,
                status=status,
                started_from=started_from,
                started_to=started_to,
            )
        ]

    @app.get("/executions/{execution_id}")
    def execution_detail(
        execution_id: int,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, requested_client_from(request, client_id))
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="execution not found")
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            raise HTTPException(status_code=404, detail="execution not found")
        run = store.get_execution_run(execution_id, client_id=scope)
        if run is None or run.id is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return {
            **_execution_run_view(run),
            "steps": [_execution_step_view(step) for step in store.list_execution_steps(run.id)],
            "artifacts": [
                _execution_artifact_view(artifact)
                for artifact in store.list_execution_artifacts(
                    run.id,
                    client_id=run.client_id if run.client_id is not None else AllClients(),
                )
            ],
        }

    @app.get("/executions/{execution_id}/artifacts/{artifact_id}")
    def execution_artifact_download(
        execution_id: int,
        artifact_id: int,
        context: TechnicianAccess,
        client_id: str | None = None,
    ) -> FileResponse:
        scope = _resolve_detail_scope(context, client_id)
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and scoped_client_id is None and not context.is_msp_admin:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        run = store.get_execution_run(execution_id, client_id=scope)
        if run is None or run.id is None:
            raise HTTPException(status_code=404, detail="execution artifact not found")
        artifact = store.get_execution_artifact(
            artifact_id,
            client_id=run.client_id if run.client_id is not None else AllClients(),
        )
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
        scope = resolve_client_scope(context, client_id)
        if isinstance(scope, BoundClients) and scope.client_id is None:
            raise HTTPException(status_code=403, detail="analytics require a single client or all-client scope")
        estimates = {manifest.action_id: manifest.estimated_minutes_saved for manifest in smart_action_service.list()}
        return build_analytics_summary(
            store,
            estimates,
            started_from=started_from,
            started_to=started_to,
            client_id=scope,
        )

    @app.post("/knowledge/ingest")
    def ingest_knowledge(
        request: KnowledgeIngestRequest,
        context: TechnicianAccess,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, request.client_id).client_id
        if scoped_client_id is None and not context.demo_mode:
            raise HTTPException(status_code=403, detail="knowledge ingestion requires a client scope")
        try:
            settings = replace(
                active_settings,
                document_parser=request.parser or active_settings.document_parser,
                allow_ocr=active_settings.allow_ocr if request.ocr is None else request.ocr,
            )
            service = ingestion_service_from_settings(store, settings)
            documents = service.ingest_path(Path(request.path), client_id=scoped_client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(document) for document in documents]

    @app.get("/knowledge/documents")
    def knowledge_documents(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [asdict(document) for document in store.list_knowledge_documents(client_id=scope)]

    @app.patch("/knowledge/documents/{document_id}/authority")
    def set_knowledge_document_authority(
        document_id: int,
        payload: KnowledgeAuthorityRequest,
        context: AdminAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, client_id)
        actor = context.approver_id or context.principal_id or "authenticated-admin"
        try:
            document = store.set_knowledge_document_authority(
                document_id,
                payload.authority,
                actor,
                client_id=scope,
                sop_version=payload.sop_version,
                superseded_by=payload.superseded_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if document is None:
            raise HTTPException(status_code=404, detail="knowledge document not found")
        return asdict(document)

    @app.get("/knowledge/search")
    def knowledge_search(
        context: ViewerAccess,
        q: str,
        limit: int = 3,
        backend: str | None = None,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        try:
            settings = replace(
                active_settings,
                vector_backend=backend or active_settings.vector_backend,
            )
            search_backend = search_backend_from_settings(settings, store)
            return [asdict(chunk) for chunk in search_backend.search(q, limit=limit, client_id=scope)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc




    ui_dist = _resolve_ui_dist()
    if ui_dist is not None:
        app.mount("/", SPAStaticFiles(directory=ui_dist), name="ui")

    return app


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


def _quarantined_ticket_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(cast(QuarantinedTicketError, exc))},
    )


def _request_validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    sensitive_fields: set[str]
    if request.url.path == "/secrets":
        sensitive_fields = {"value"}
    elif request.url.path == "/auth/login/local":
        sensitive_fields = {"token"}
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
