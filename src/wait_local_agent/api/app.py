from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import cast

from fastapi import Depends, FastAPI, HTTPException, Request, Response  # noqa: F401
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
    ApiContext,
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
from wait_local_agent.api.routers.end_user import create_end_user_router
from wait_local_agent.api.routers.knowledge import create_knowledge_router
from wait_local_agent.api.routers.m365 import create_m365_router
from wait_local_agent.api.routers.msp_playbooks import create_msp_playbooks_router
from wait_local_agent.api.routers.operations import create_operations_router
from wait_local_agent.api.routers.psa_connectors import create_psa_connectors_router
from wait_local_agent.api.routers.scheduled_jobs import create_scheduled_jobs_router
from wait_local_agent.api.routers.system import create_system_router
from wait_local_agent.api.routers.tenancy import create_tenancy_router
from wait_local_agent.api.routers.tickets import create_tickets_router
from wait_local_agent.api.routers.workflows import create_workflows_router

# Compatibility exports. Names re-exported below remain importable from wait_local_agent.api.app
# because tests import or resolve them here; tests/test_client_scope_enforcement.py resolves the
# scope helpers by name at runtime. Everything else moved to api.schemas, api.scopes, api.views and
# api.routers.*; import it from there.
from wait_local_agent.api.schemas import (
    AgentApprovalRuleRequest,  # noqa: F401
    AgentStepRequest,  # noqa: F401
    EndUserMessageRequest,  # noqa: F401
    EvaluationExecutionRequest,  # noqa: F401
    QuarantineReclassificationRequest,  # noqa: F401
    TeamsMessageDraftRequest,  # noqa: F401
)

# Kept importable from api.app: tests/test_client_scope_enforcement.py resolves these helpers by name at runtime.
from wait_local_agent.api.scopes import (
    _approval_scope_visible,  # noqa: F401
    _backfill_scope,  # noqa: F401
    _connector_read_client,  # noqa: F401, RUF100
    _end_user_read_client_id,  # noqa: F401
    _operator_scope,  # noqa: F401
    _required_client_id,  # noqa: F401
    _resolve_client_target_scope,  # noqa: F401
    _resolve_detail_scope,  # noqa: F401
    _scope_contains_client,  # noqa: F401
)
from wait_local_agent.api.views import (
    _EXECUTING_EXECUTION_STATUS,  # noqa: F401
    SENSITIVE_KEY_PARTS,  # noqa: F401
    _empty_analytics_summary,  # noqa: F401
    _halopsa_client_mapping,  # noqa: F401
    _invoke_technician_chat_message,  # noqa: F401
    _record_technician_chat_assistant,  # noqa: F401
    _redact_json_text,  # noqa: F401
    _redact_payload,  # noqa: F401
    _redact_request_input,
    _redact_value,  # noqa: F401
    _safe_external_ticket_id,  # noqa: F401
    _safe_json_list,  # noqa: F401
    _safe_json_object,  # noqa: F401
    _safe_json_value,  # noqa: F401
    _safe_json_values,  # noqa: F401
    _safe_redacted_json_object,  # noqa: F401
    make_approval_view,
)
from wait_local_agent.autotask import AutotaskClient
from wait_local_agent.baseline import BaselineService
from wait_local_agent.client_scope import (
    AllClients,
)
from wait_local_agent.collectors import (
    CollectorService,
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
    build_read_client_for_client,  # noqa: F401
)
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.diagnostics import (
    valid_correlation_id,
)
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.founder_bundle import PrivacyViolation
from wait_local_agent.halopsa import HaloPSAClient
from wait_local_agent.hudu import HuduClient
from wait_local_agent.ingestion_poller import IngestionPoller
from wait_local_agent.itglue import ItGlueClient
from wait_local_agent.lp_client import (
    LaunchPassportError,
    LaunchPassportForbidden,
    LaunchPassportPayloadTooLarge,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
)
from wait_local_agent.m365_auth import M365ConnectionResolver
from wait_local_agent.m365_graph import (
    M365GraphClient,
)
from wait_local_agent.mcp import (
    WaitMcpServer,
)
from wait_local_agent.notion import NotionClient
from wait_local_agent.oidc import get_or_create_session_signing_key
from wait_local_agent.operational_graph import OperationalGraphService
from wait_local_agent.providers import (
    provider_from_settings,
)
from wait_local_agent.rbac import (
    Role,
    admin_credential_configured,
    require_role,
    resolve_auth_context,  # noqa: F401
)
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
    QuarantinedTicketError,
    Store,
)
from wait_local_agent.syncro import SyncroClient
from wait_local_agent.teams_graph import TeamsGraphClient
from wait_local_agent.timezest import TimeZestClient
from wait_local_agent.update_channel import UpdateStatusCache
from wait_local_agent.vault import SecretVault
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

    connector_read_client = partial(
        _connector_read_client,
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
        connector_read_client=connector_read_client,
        approval_view=_approval_view,
    )

    mount_flat(app, create_system_router(ctx))

    mount_flat(app, create_tickets_router(ctx))

    mount_flat(app, create_tenancy_router(ctx))

    mount_flat(app, create_automation_router(ctx))
    mount_flat(app, create_agents_router(ctx))
    mount_flat(app, create_end_user_router(ctx))

    mount_flat(app, create_operations_router(ctx))
    mount_flat(app, create_psa_connectors_router(ctx))

    mount_flat(app, create_documentation_connectors_router(ctx))

    mount_flat(app, create_m365_router(ctx))


    mount_flat(app, create_workflows_router(ctx))

    mount_flat(app, create_msp_playbooks_router(ctx))

    mount_flat(app, create_consultant_router(ctx))

    mount_flat(app, create_scheduled_jobs_router(ctx))

    mount_flat(app, create_knowledge_router(ctx))
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
