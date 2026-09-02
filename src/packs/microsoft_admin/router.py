"""FastAPI surface for the Microsoft administrator pack."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from packs.azure_lighthouse.router import create_router as create_azure_lighthouse_router
from packs.microsoft_admin.core import (
    MAX_CURSOR_LENGTH,
    MAX_PAGE_SIZE,
    MicrosoftAdminError,
    MicrosoftAdminGraphClient,
    build_dashboard,
    diagnose_access,
    remediation_catalog,
)
from packs.microsoft_admin.runbooks import (
    ExecutableResolver,
    PlatformPredicate,
    RunbookApprovalError,
    RunbookError,
    RunbookRunner,
    build_runbook_plan,
    create_runbook_approval,
    execute_approved_runbook,
    runbook_catalog,
    runbook_runtime_status,
)
from wait_local_agent.capabilities import MICROSOFT_ADMIN_CAPABILITY
from wait_local_agent.config import Settings
from wait_local_agent.m365_auth import M365ProfileResolutionError
from wait_local_agent.m365_graph import M365GraphClient, M365GraphReadError
from wait_local_agent.rbac import AuthContext, Role, require_capability_scope, require_role
from wait_local_agent.store import Store

PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Cursor = Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)]
ClientID = Annotated[str | None, Query(max_length=128)]
TechnicianAccess = Annotated[AuthContext, Depends(require_role(Role.TECHNICIAN))]
AdminAccess = Annotated[AuthContext, Depends(require_role(Role.ADMIN))]


class AccessDiagnosticRequest(BaseModel):
    user_identity: str = Field(min_length=3, max_length=320)
    device_name: str | None = Field(default=None, max_length=256)

    model_config = ConfigDict(extra="forbid")


class RunbookPlanRequest(BaseModel):
    runbook_id: str = Field(min_length=3, max_length=120)
    parameters: dict[str, object] = Field(default_factory=dict, max_length=16)
    client_id: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")


def create_router() -> APIRouter:
    router = APIRouter(tags=["Microsoft administrator"])
    router.include_router(create_azure_lighthouse_router(), prefix="/azure-lighthouse")

    @router.get("/health")
    @router.get("/status")
    def status(request: Request, client_id: ClientID = None) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return asdict(client.health())

    @router.get("/dashboard")
    def dashboard(request: Request, client_id: ClientID = None) -> dict[str, object]:
        client, core_client = _clients_for(request, client_id)
        result = build_dashboard(client, core_client)
        _audit(request, "microsoft_admin.dashboard", "tenant", str(result["status"]))
        return result

    @router.get("/users")
    def users(
        request: Request,
        client_id: ClientID = None,
        identity: str | None = Query(default=None, max_length=320),
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        _, core_client = _clients_for(request, client_id)
        response = core_client.list_users(identity=identity, page_size=page_size, cursor=cursor)
        return _core_response(response)

    @router.get("/groups")
    def groups(
        request: Request,
        client_id: ClientID = None,
        identity: str | None = Query(default=None, max_length=320),
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        _, core_client = _clients_for(request, client_id)
        response = core_client.list_groups(identity=identity, page_size=page_size, cursor=cursor)
        return _core_response(response)

    @router.get("/licenses")
    def licenses(
        request: Request,
        client_id: ClientID = None,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        _, core_client = _clients_for(request, client_id)
        return _core_response(core_client.list_subscribed_skus(cursor=cursor))

    @router.get("/devices")
    def devices(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        _, core_client = _clients_for(request, client_id)
        return _core_response(core_client.list_managed_devices(page_size=page_size, cursor=cursor))

    @router.get("/service-health")
    def service_health(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_service_health(page_size=page_size, cursor=cursor))

    @router.get("/service-issues")
    def service_issues(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_service_issues(page_size=page_size, cursor=cursor))

    @router.get("/security/secure-score")
    def secure_score(
        request: Request,
        client_id: ClientID = None,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_secure_scores(page_size=1, cursor=cursor))

    @router.get("/security/incidents")
    def security_incidents(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_defender_incidents(page_size=page_size, cursor=cursor))

    @router.get("/security/alerts")
    def security_alerts(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_defender_alerts(page_size=page_size, cursor=cursor))

    @router.get("/identity/sign-ins")
    def sign_ins(
        request: Request,
        client_id: ClientID = None,
        identity: str | None = Query(default=None, max_length=320),
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_sign_ins(identity=identity, page_size=page_size, cursor=cursor))

    @router.get("/identity/conditional-access")
    def conditional_access(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_conditional_access_policies(page_size=page_size, cursor=cursor))

    @router.get("/identity/risky-users")
    def risky_users(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_risky_users(page_size=page_size, cursor=cursor))

    @router.get("/endpoint/apps")
    def endpoint_apps(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_intune_apps(page_size=page_size, cursor=cursor))

    @router.get("/endpoint/compliance-policies")
    def compliance_policies(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_compliance_policies(page_size=page_size, cursor=cursor))

    @router.get("/endpoint/autopilot")
    def autopilot_devices(
        request: Request,
        client_id: ClientID = None,
        page_size: PageSize = 25,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        client, _ = _clients_for(request, client_id)
        return _admin_response(client.list_autopilot_devices(page_size=page_size, cursor=cursor))

    @router.post("/diagnostics/access")
    def access_diagnostic(
        payload: AccessDiagnosticRequest,
        request: Request,
        client_id: ClientID = None,
    ) -> dict[str, object]:
        client, core_client = _clients_for(request, client_id)
        try:
            result = diagnose_access(
                client,
                core_client,
                user_identity=payload.user_identity,
                device_name=payload.device_name,
            )
        except MicrosoftAdminError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        outcome = (
            "attention"
            if any(item.severity in {"high", "critical"} for item in result.findings)
            else "review"
        )
        _audit(request, "microsoft_admin.access_diagnostic", "access", outcome)
        return result.to_dict()

    @router.get("/remediations")
    def remediations() -> list[dict[str, object]]:
        return remediation_catalog()

    @router.get("/runbooks")
    def runbooks() -> list[dict[str, object]]:
        return runbook_catalog()

    @router.get("/runbooks/status")
    def runbooks_status(request: Request) -> dict[str, object]:
        settings = cast(Settings, request.app.state.settings)
        _, resolver, predicate = _runbook_dependencies(request)
        return runbook_runtime_status(
            settings,
            executable_resolver=resolver,
            platform_is_windows=predicate,
        ).to_dict()

    @router.post("/runbooks/plan")
    def runbook_plan(
        payload: RunbookPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        client_id = _scoped_client_id(context, payload.client_id)
        try:
            return build_runbook_plan(
                payload.runbook_id,
                payload.parameters,
                client_id=client_id,
            )
        except RunbookError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/runbooks/drafts")
    def runbook_draft(
        payload: RunbookPlanRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        store = _store(request)
        client_id = _scoped_client_id(context, payload.client_id)
        try:
            approval, plan = create_runbook_approval(
                store,
                client_id=client_id,
                runbook_id=payload.runbook_id,
                parameters=payload.parameters,
            )
        except RunbookError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"approval": asdict(approval), "plan": plan}

    @router.post("/runbooks/approvals/{request_id}/execute")
    def runbook_execute(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        store = _store(request)
        approval = store.get_approval_request(request_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="PowerShell runbook approval was not found.")
        if not approval.client_id:
            raise HTTPException(status_code=409, detail="PowerShell runbook approval has no tenant.")
        _scoped_client_id(context, approval.client_id)
        runner, resolver, predicate = _runbook_dependencies(request)
        settings = cast(Settings, request.app.state.settings)
        try:
            updated, result = execute_approved_runbook(
                store,
                request_id,
                settings,
                expected_client_id=approval.client_id,
                runner=runner,
                executable_resolver=resolver,
                platform_is_windows=predicate,
            )
        except RunbookApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RunbookError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"approval": asdict(updated), "result": result.to_dict()}

    return router


def _clients_for(
    request: Request,
    client_id: str | None,
) -> tuple[MicrosoftAdminGraphClient, M365GraphClient]:
    settings = cast(Settings, request.app.state.settings)
    effective_client_id = client_id.strip() if isinstance(client_id, str) and client_id.strip() else None
    if effective_client_id is None:
        effective_client_id = cast(str | None, getattr(request.state, "capability_client_id", None))
    connection_resolver = getattr(request.app.state, "m365_connection_resolver", None)
    admin_transport = cast(
        httpx.BaseTransport | None,
        getattr(request.app.state, "microsoft_admin_transport", None),
    )
    m365_transport = cast(
        httpx.BaseTransport | None,
        getattr(request.app.state, "m365_transport", None),
    )
    if connection_resolver is None:
        return (
            MicrosoftAdminGraphClient(settings, transport=admin_transport, client_id=effective_client_id),
            M365GraphClient(settings, transport=m365_transport, client_id=effective_client_id),
        )
    try:
        connection = connection_resolver.resolve(effective_client_id)
    except M365ProfileResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return (
        MicrosoftAdminGraphClient(
            settings,
            transport=admin_transport,
            connection=connection,
            client_id=effective_client_id,
        ),
        M365GraphClient(
            settings,
            transport=m365_transport,
            connection=connection,
            client_id=effective_client_id,
        ),
    )


def _core_response(response: Any) -> dict[str, object]:
    _raise_m365_graph_http_error(getattr(response, "error", None))
    return {
        "result": asdict(response.result),
        "items": [asdict(item) for item in response.items],
        "next_cursor": response.next_cursor,
    }


def _admin_response(response: Any) -> dict[str, object]:
    _raise_m365_graph_http_error(getattr(response, "error", None))
    return response.to_dict()


def _raise_m365_graph_http_error(error: object) -> None:
    if not isinstance(error, M365GraphReadError) or error.code is None:
        return
    status_code = {
        "m365_throttled": 429,
        "m365_auth_required": 502,
        "m365_insufficient_permission": 403,
        "m365_unavailable": 503,
        "m365_pagination_failed": 502,
    }.get(error.code, 502)
    detail: dict[str, object] = {"code": error.code, "message": error.message}
    if error.retry_after is not None:
        detail["retry_after_seconds"] = max(0, round(error.retry_after))
    raise HTTPException(status_code=status_code, detail=detail)


def _store(request: Request) -> Store:
    store = cast(Store | None, getattr(request.app.state, "store", None))
    if store is None:
        raise HTTPException(status_code=503, detail="Local approval store is unavailable.")
    return store


def _scoped_client_id(context: AuthContext, requested_client_id: str | None) -> str:
    return require_capability_scope(
        context,
        MICROSOFT_ADMIN_CAPABILITY,
        requested_client_id,
    )


def _runbook_dependencies(
    request: Request,
) -> tuple[RunbookRunner | None, ExecutableResolver | None, PlatformPredicate | None]:
    runner = cast(
        RunbookRunner | None,
        getattr(request.app.state, "microsoft_admin_runbook_runner", None),
    )
    resolver = cast(
        ExecutableResolver | None,
        getattr(request.app.state, "microsoft_admin_powershell_resolver", None),
    )
    predicate = cast(
        PlatformPredicate | None,
        getattr(request.app.state, "microsoft_admin_windows_predicate", None),
    )
    return runner, resolver, predicate


def _audit(request: Request, event_type: str, entity_id: str, status: str) -> None:
    store = cast(Store | None, getattr(request.app.state, "store", None))
    if store is not None:
        store.add_audit_event(event_type, entity_id, status)
