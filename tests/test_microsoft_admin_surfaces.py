from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from microsoft_admin_support import _configured
from starlette.requests import Request
from typer.testing import CliRunner

from packs.microsoft_admin.cli import app as microsoft_admin_cli
from packs.microsoft_admin.core import MicrosoftAdminError
from packs.microsoft_admin.models import MicrosoftAdminReadResponse
from packs.microsoft_admin.router import RunbookPlanRequest, _admin_response, create_router
from packs.microsoft_admin.runbooks import RunbookApprovalError, RunbookError
from wait_local_agent.m365_auth import M365ConnectionResolver
from wait_local_agent.m365_graph import M365ThrottledError
from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault


def test_admin_response_preserves_pack_items_and_raises_typed_errors() -> None:
    response = MicrosoftAdminReadResponse(
        ConnectorReadResult("ready", "ready", 1),
        [{"id": "service-1", "status": "serviceOperational"}],
        next_cursor="next-page",
    )

    assert _admin_response(response) == {
        "result": {"status": "ready", "message": "ready", "count": 1, "tier": None},
        "items": [{"id": "service-1", "status": "serviceOperational"}],
        "next_cursor": "next-page",
    }

    failed = MicrosoftAdminReadResponse(
        ConnectorReadResult("failed", "rate limited"),
        [],
        error=M365ThrottledError("rate limited", retry_after=4),
    )
    with pytest.raises(HTTPException) as error:
        _admin_response(failed)
    assert error.value.status_code == 429
    assert error.value.detail == {
        "code": "m365_throttled",
        "message": "rate limited",
        "retry_after_seconds": 4,
    }


def _request_for_app(app: FastAPI, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
            "root_path": "",
            "app": app,
        }
    )


def test_router_exposes_real_reads_dashboard_diagnostic_and_audit(settings) -> None:
    configured = _configured(settings)

    def admin_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        rows: list[dict[str, object]] = []
        if path.endswith("/healthOverviews"):
            rows = [{"id": "Exchange", "service": "Exchange Online", "status": "serviceOperational"}]
        elif path.endswith("/secureScores"):
            rows = [{"id": "score", "currentScore": 80, "maxScore": 100}]
        elif path.endswith("/policies"):
            rows = [{"id": "ca-1", "displayName": "Require MFA", "state": "enabled"}]
        return httpx.Response(200, json={"value": rows})

    def m365_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/users"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "user-1",
                            "displayName": "Adele Vance",
                            "userPrincipalName": "adele@example.test",
                            "mail": "adele@example.test",
                            "accountEnabled": True,
                            "jobTitle": "Admin",
                            "department": "IT",
                        }
                    ]
                },
            )
        if path.endswith("/licenseDetails"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "license-1",
                            "skuId": "11111111-1111-1111-1111-111111111111",
                            "skuPartNumber": "ENTERPRISEPACK",
                            "servicePlans": [],
                        }
                    ]
                },
            )
        if path.endswith("/managedDevices"):
            return httpx.Response(200, json={"value": []})
        raise AssertionError(path)

    class AuditStore:
        def __init__(self) -> None:
            self.events: list[tuple[str, str, str]] = []

        def add_audit_event(self, event_type: str, entity_id: str, status: str) -> None:
            self.events.append((event_type, entity_id, status))

    app = FastAPI()
    app.state.settings = configured
    app.state.microsoft_admin_transport = httpx.MockTransport(admin_handler)
    app.state.m365_transport = httpx.MockTransport(m365_handler)
    audit_store = AuditStore()
    app.state.store = audit_store
    app.include_router(create_router(), prefix="/packs/microsoft-admin")
    client = TestClient(app)

    assert client.get("/packs/microsoft-admin/status").status_code == 200
    service = client.get("/packs/microsoft-admin/service-health")
    assert service.status_code == 200
    assert service.json()["items"][0]["service"] == "Exchange Online"
    assert client.get("/packs/microsoft-admin/service-health?page_size=101").status_code == 422
    dashboard_response = client.get("/packs/microsoft-admin/dashboard")
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["summary"]["secure_score_percent"] == 80.0
    diagnostic_response = client.post(
        "/packs/microsoft-admin/diagnostics/access",
        json={"user_identity": "adele@example.test"},
    )
    assert diagnostic_response.status_code == 200
    assert diagnostic_response.json()["findings"][0]["code"] == "no-direct-cause-observed"
    assert client.get("/packs/microsoft-admin/remediations").status_code == 200
    assert [event[0] for event in audit_store.events] == [
        "microsoft_admin.dashboard",
        "microsoft_admin.access_diagnostic",
    ]

    invalid = client.post(
        "/packs/microsoft-admin/diagnostics/access",
        json={"user_identity": "bad\nidentity"},
    )
    assert invalid.status_code == 400


def test_pack_users_route_uses_the_authorized_client_connector(settings, tmp_path) -> None:
    configured = _configured(settings)
    store = Store(configured.data_path)
    store.create_client("client-a", "Client A")
    client_instance = store.create_connector_instance(
        "m365",
        "Client A Graph",
        client_id="client-a",
        credential_ref="m365-client-a",
    )
    msp_instance = store.create_connector_instance(
        "m365",
        "MSP Graph",
        credential_ref="m365-msp",
    )
    store.update_connector_instance(client_instance.connector_instance_id, status="active")
    store.update_connector_instance(msp_instance.connector_instance_id, status="active")
    vault = SecretVault.initialize(tmp_path / "vault")
    vault.set("m365-client-a", '{"mode":"static_token","access_token":"client-a-token"}')
    vault.set("m365-msp", '{"mode":"static_token","access_token":"msp-token"}')
    seen_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_tokens.append(request.headers["Authorization"])
        return httpx.Response(200, json={"value": []})

    app = FastAPI()
    app.state.settings = configured
    app.state.store = store
    app.state.vault = vault
    app.state.m365_connection_resolver = M365ConnectionResolver(configured, store, vault)
    app.state.microsoft_admin_transport = httpx.MockTransport(handler)
    app.state.m365_transport = httpx.MockTransport(handler)
    request = _request_for_app(app, "/users")
    routes = {
        route.path: cast(APIRoute, route)
        for route in create_router().routes
        if isinstance(route, APIRoute)
    }

    result = routes["/users"].endpoint(
        request,
        client_id="client-a",
        identity=None,
        page_size=25,
        cursor=None,
    )
    groups_result = routes["/groups"].endpoint(
        request,
        client_id="client-a",
        identity=None,
        page_size=25,
        cursor=None,
    )
    sign_ins_result = routes["/identity/sign-ins"].endpoint(
        request,
        client_id="client-a",
        identity=None,
        page_size=25,
        cursor=None,
    )
    licenses_result = routes["/licenses"].endpoint(request, client_id="client-a", cursor=None)
    devices_result = routes["/devices"].endpoint(
        request,
        client_id="client-a",
        page_size=25,
        cursor=None,
    )
    status_result = routes["/status"].endpoint(request, client_id="client-a")

    assert result["result"]["status"] == "ready"
    assert groups_result["result"]["status"] == "ready"
    assert sign_ins_result["result"]["status"] == "ready"
    assert licenses_result["result"]["status"] == "ready"
    assert devices_result["result"]["status"] == "ready"
    assert status_result["status"] == "ready"
    assert len(seen_tokens) >= 4
    assert set(seen_tokens) == {"Bearer client-a-token"}


def test_pack_client_scope_fails_before_graph_when_only_msp_connector_exists(settings, tmp_path) -> None:
    configured = _configured(settings)
    store = Store(configured.data_path)
    store.create_client("client-a", "Client A")
    msp_instance = store.create_connector_instance(
        "m365",
        "MSP Graph",
        credential_ref="m365-msp",
    )
    store.update_connector_instance(msp_instance.connector_instance_id, status="active")
    vault = SecretVault.initialize(tmp_path / "vault")
    vault.set("m365-msp", '{"mode":"static_token","access_token":"msp-token"}')
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"value": []})

    app = FastAPI()
    app.state.settings = configured
    app.state.store = store
    app.state.vault = vault
    app.state.m365_connection_resolver = M365ConnectionResolver(configured, store, vault)
    app.state.m365_transport = httpx.MockTransport(handler)
    request = _request_for_app(app, "/users")
    route = cast(APIRoute, next(route for route in create_router().routes if getattr(route, "path", None) == "/users"))

    with pytest.raises(HTTPException) as error:
        route.endpoint(request, client_id="client-a")

    assert error.value.status_code == 409
    assert "client-a" in str(error.value.detail)
    assert "client-scoped" in str(error.value.detail)
    assert calls == []


def test_router_maps_runbook_and_store_failures_without_leaking_details(settings, monkeypatch) -> None:
    import packs.microsoft_admin.router as router_module

    app = FastAPI()
    app.state.settings = _configured(settings)
    request = _request_for_app(app, "/runbooks/drafts")
    routes = {
        route.path: cast(APIRoute, route).endpoint
        for route in create_router().routes
        if isinstance(route, APIRoute)
    }
    draft_payload = RunbookPlanRequest(runbook_id="windows.service_restart")

    with pytest.raises(HTTPException) as missing_store:
        routes["/runbooks/drafts"](draft_payload, request, object())
    assert missing_store.value.status_code == 503

    monkeypatch.setattr(router_module, "_store", lambda _request: object())
    monkeypatch.setattr(router_module, "_scoped_client_id", lambda *_args: "client-a")

    def reject_draft(*_args, **_kwargs):
        raise RunbookError("invalid runbook parameters")

    monkeypatch.setattr(router_module, "create_runbook_approval", reject_draft)
    with pytest.raises(HTTPException) as rejected_draft:
        routes["/runbooks/drafts"](draft_payload, request, object())
    assert rejected_draft.value.status_code == 422

    class ApprovalStore:
        def __init__(self, client_id: str | None) -> None:
            self.approval = SimpleNamespace(client_id=client_id)

        def get_approval_request(self, _request_id: int):
            return self.approval

    monkeypatch.setattr(router_module, "_store", lambda _request: ApprovalStore(None))
    with pytest.raises(HTTPException) as missing_tenant:
        routes["/runbooks/approvals/{request_id}/execute"](1, request, object())
    assert missing_tenant.value.status_code == 409

    monkeypatch.setattr(router_module, "_store", lambda _request: ApprovalStore("client-a"))
    monkeypatch.setattr(router_module, "_runbook_dependencies", lambda _request: (None, None, None))
    for failure, expected_status in (
        (RunbookApprovalError("approval conflict"), 409),
        (RunbookError("invalid stored plan"), 422),
    ):
        def reject_execution(*_args, error=failure, **_kwargs):
            raise error

        monkeypatch.setattr(router_module, "execute_approved_runbook", reject_execution)
        with pytest.raises(HTTPException) as rejected_execution:
            routes["/runbooks/approvals/{request_id}/execute"](1, request, object())
        assert rejected_execution.value.status_code == expected_status


def test_cli_lists_available_approval_gated_remediations() -> None:
    result = CliRunner().invoke(microsoft_admin_cli, ["remediations"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["action_id"] == "m365-managed-device-sync"


def test_router_exposes_each_bounded_read_surface(settings) -> None:
    configured = _configured(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": []})

    app = FastAPI()
    app.state.settings = configured
    app.state.microsoft_admin_transport = httpx.MockTransport(handler)
    app.state.m365_transport = httpx.MockTransport(handler)
    app.include_router(create_router(), prefix="/packs/microsoft-admin")
    client = TestClient(app)

    paths = [
        "/service-issues",
        "/security/secure-score",
        "/security/incidents",
        "/security/alerts",
        "/identity/sign-ins?identity=adele@example.test",
        "/identity/conditional-access",
        "/identity/risky-users",
        "/endpoint/apps",
        "/endpoint/compliance-policies",
        "/endpoint/autopilot",
    ]
    for path in paths:
        response = client.get(f"/packs/microsoft-admin{path}")
        assert response.status_code == 200
        assert response.json()["result"]["status"] == "ready"

    # Dashboard without a Store still succeeds and deliberately omits audit persistence.
    assert client.get("/packs/microsoft-admin/dashboard").status_code == 200


def test_cli_status_dashboard_and_diagnostic_commands(monkeypatch) -> None:
    import packs.microsoft_admin.cli as cli_module

    class FakeAdminClient:
        def __init__(self, settings) -> None:
            self.settings = settings

        def health(self) -> ConnectorReadResult:
            return ConnectorReadResult("ready", "ready", 1)

    class FakeCoreClient:
        def __init__(self, settings) -> None:
            self.settings = settings

    class FakeDiagnostic:
        def to_dict(self) -> dict[str, object]:
            return {"probable_root_cause": "Device is noncompliant"}

    monkeypatch.setattr(cli_module, "load_settings", lambda: object())
    monkeypatch.setattr(cli_module, "MicrosoftAdminGraphClient", FakeAdminClient)
    monkeypatch.setattr(cli_module, "M365GraphClient", FakeCoreClient)
    monkeypatch.setattr(cli_module, "build_dashboard", lambda admin, core: {"status": "ready"})
    monkeypatch.setattr(
        cli_module,
        "diagnose_access",
        lambda admin, core, user_identity, device_name: FakeDiagnostic(),
    )

    runner = CliRunner()
    status_result = runner.invoke(microsoft_admin_cli, ["status"])
    dashboard_result = runner.invoke(microsoft_admin_cli, ["dashboard"])
    diagnostic_result = runner.invoke(
        microsoft_admin_cli,
        ["diagnose-access", "--user", "adele@example.test", "--device", "LAPTOP-001"],
    )

    assert status_result.exit_code == 0
    assert json.loads(status_result.output)["status"] == "ready"
    assert dashboard_result.exit_code == 0
    assert json.loads(dashboard_result.output) == {"status": "ready"}
    assert diagnostic_result.exit_code == 0
    assert json.loads(diagnostic_result.output)["probable_root_cause"] == "Device is noncompliant"

    def fail_diagnostic(admin, core, user_identity, device_name):
        raise MicrosoftAdminError("invalid identity")

    monkeypatch.setattr(cli_module, "diagnose_access", fail_diagnostic)
    failed = runner.invoke(microsoft_admin_cli, ["diagnose-access", "--user", "bad"])
    assert failed.exit_code == 2
    assert "invalid identity" in failed.output
