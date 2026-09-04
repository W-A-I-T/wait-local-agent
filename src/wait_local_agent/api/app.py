from __future__ import annotations

import csv
import io
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
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
from wait_local_agent.agents import AgentService
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
from wait_local_agent.api.routers.agents import create_agents_router
from wait_local_agent.api.routers.automation import create_automation_router
from wait_local_agent.api.routers.consultant import create_consultant_router
from wait_local_agent.api.routers.documentation_connectors import create_documentation_connectors_router
from wait_local_agent.api.routers.m365 import create_m365_router
from wait_local_agent.api.routers.msp_playbooks import create_msp_playbooks_router
from wait_local_agent.api.routers.psa_connectors import create_psa_connectors_router
from wait_local_agent.api.routers.scheduled_jobs import create_scheduled_jobs_router
from wait_local_agent.api.routers.system import create_system_router
from wait_local_agent.api.routers.workflows import create_workflows_router
from wait_local_agent.api.schemas import (
    AgentApprovalRuleRequest,  # noqa: F401
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
    DeploymentModeRequest,
    DiagnosticsBundleRequest,
    DiagnosticsUploadRequest,
    EndUserBrandingResponse,
    EndUserHaloSyncDraftRequest,
    EndUserMessageRequest,
    EndUserTicketCreateRequest,
    EvaluationExecutionRequest,  # noqa: F401
    HardeningRunRequest,
    KnowledgeAuthorityRequest,
    KnowledgeIngestRequest,
    QuarantineReclassificationRequest,
    RestoreExerciseRequest,
    SecretSetRequest,
    TeamsMessageDraftRequest,  # noqa: F401
    TechnicianChatMessageRequest,
    TechnicianChatRequest,
    TechnicianChatSessionCreateRequest,
)
from wait_local_agent.api.scopes import (
    _approval_scope_visible,
    _backfill_scope,  # noqa: F401
    _connector_read_client,  # noqa: F401
    _end_user_client_id,
    _end_user_read_client_id,
    _operator_scope,
    _request_correlation_id,
    _require_commercial_activation_access,
    _require_msp_operator,
    _required_client_id,  # noqa: F401
    _resolve_client_target_scope,
    _resolve_detail_scope,
    _scope_contains_client,  # noqa: F401
    _singular_action_client,
)
from wait_local_agent.api.views import (
    _EXECUTING_EXECUTION_STATUS,  # noqa: F401
    SENSITIVE_KEY_PARTS,  # noqa: F401
    _baseline_view,
    _empty_analytics_summary,  # noqa: F401
    _end_user_brand_color,
    _end_user_brand_logo_data_uri,
    _end_user_branding_text,
    _end_user_message_view,
    _end_user_ticket_view,
    _halopsa_client_mapping,
    _halopsa_draft_view,
    _invoke_technician_chat_message,
    _operator_end_user_message_view,
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
    _safe_json_values,  # noqa: F401
    _safe_redacted_json_object,  # noqa: F401
    _scheduled_job_view,
    _technician_chat_session_view,
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
    list_secret_records,
    update_connectwise_approval_fields,
    update_halopsa_approval_fields,
)
from wait_local_agent.connectwise import ConnectWiseClient
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
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.founder_bundle import PrivacyViolation
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
    WaitMcpServer,
)
from wait_local_agent.models import (
    ClientCandidate,
    ConnectorInstance,
)
from wait_local_agent.notion import NotionClient
from wait_local_agent.oidc import get_or_create_session_signing_key
from wait_local_agent.operational_graph import OperationalGraphService
from wait_local_agent.providers import (
    provider_from_settings,
)
from wait_local_agent.rbac import (
    AuthContext,
    Role,
    admin_credential_configured,
    require_role,
    resolve_auth_context,  # noqa: F401
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
from wait_local_agent.scheduler import SchedulerManager
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
from wait_local_agent.syncro import SyncroClient
from wait_local_agent.teams_graph import TeamsGraphClient
from wait_local_agent.technician_chat import TechnicianChatParseError
from wait_local_agent.timezest import TimeZestClient
from wait_local_agent.update_channel import UpdateStatusCache
from wait_local_agent.vault import SecretVault, SecretVaultError
from wait_local_agent.vector_search import search_backend_from_settings
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

    mount_flat(app, create_automation_router(ctx))
    mount_flat(app, create_agents_router(ctx))
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


    mount_flat(app, create_workflows_router(ctx))

    mount_flat(app, create_msp_playbooks_router(ctx))

    mount_flat(app, create_consultant_router(ctx))

    mount_flat(app, create_scheduled_jobs_router(ctx))

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
