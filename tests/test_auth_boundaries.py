from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

import wait_local_agent.api.app as app_module
import wait_local_agent.api.scopes as scopes_module
from tests.support import ensure_test_clients
from wait_local_agent.autotask import AutotaskReadResponse
from wait_local_agent.connector_factory import ConnectorFactoryError
from wait_local_agent.connectwise import ConnectWiseReadResponse
from wait_local_agent.m365_auth import M365Connection, M365ProfileResolutionError
from wait_local_agent.m365_graph import M365GraphReadResponse, M365GraphUser
from wait_local_agent.models import ConnectorReadResult, utc_now
from wait_local_agent.rbac import resolve_auth_context
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault


def test_live_api_requires_a_token_for_high_risk_reads(live_client) -> None:
    for path in ("/clients", "/approval-requests", "/audit", "/secrets"):
        response = live_client.get(path)

        assert response.status_code == 401
        assert response.json()["detail"] == "missing bearer token"


def test_viewer_bootstrap_token_can_read_but_cannot_create_clients(live_client, live_settings) -> None:
    store = Store(live_settings.data_path)
    ensure_test_clients(store, "alpha", "beta")
    live_client.set_authorization("test-viewer-token")

    clients = live_client.get("/clients")
    approvals = live_client.get("/approval-requests")
    audit = live_client.get("/audit")
    create = live_client.post("/clients", json={"client_id": "gamma", "name": "Gamma"})

    assert clients.status_code == 200
    assert {item["client_id"] for item in clients.json()} >= {"alpha", "beta"}
    # Bootstrap viewer credentials intentionally have appliance-wide read scope;
    # use database principals for per-client access. See the Bootstrap token
    # scope paragraph in docs/getting-started/configuration.md.
    assert approvals.status_code == 200
    assert approvals.json() == []
    assert audit.status_code == 200
    assert audit.json() == []
    assert create.status_code == 403
    assert create.json()["detail"] == "insufficient role"


def test_technician_bootstrap_token_cannot_read_secrets_or_manage_principals(live_client) -> None:
    live_client.set_authorization("test-tech-token")

    secrets = live_client.get("/secrets")
    principals = live_client.get("/auth/principals")

    assert secrets.status_code == 403
    assert principals.status_code == 403
    assert secrets.json()["detail"] == "insufficient role"
    assert principals.json()["detail"] == "insufficient role"


def test_cookie_session_requires_csrf_for_state_changes(live_client, live_settings) -> None:
    store = Store(live_settings.data_path)
    store.create_principal("session-admin", kind="staff")
    store.add_principal_credential("session-admin", "session-admin-secret")
    store.add_principal_global_role("session-admin")

    login = live_client.post("/auth/login/local", json={"token": "session-admin-secret"})
    assert login.status_code == 200
    assert login.json()["session_created"] is True

    missing_csrf = live_client.put("/setup/mode", json={"mode": "msp"})
    with_csrf = live_client.put(
        "/setup/mode",
        headers={"X-WAIT-CSRF": "test-csrf"},
        json={"mode": "msp"},
    )

    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"]["code"] == "csrf_required"
    assert with_csrf.status_code == 200
    assert with_csrf.json()["mode"] == "msp"


def test_live_approval_suite_uses_viewer_read_and_rejects_viewer_decision(live_client, live_settings) -> None:
    """Live-fixture twin for approval tests: auth must precede approval behavior."""

    store = Store(live_settings.data_path)
    ensure_test_clients(store, "alpha")
    approval = store.create_approval_request(
        "TCK-LIVE-APPROVAL",
        "ticket.assign",
        {"ticket_id": "TCK-LIVE-APPROVAL"},
        client_id="alpha",
    )
    live_client.set_authorization("test-viewer-token")

    detail = live_client.get(f"/approval-requests/{approval.id}")
    decision = live_client.post(
        f"/approval-requests/{approval.id}",
        json={"status": "approved", "comment": "viewer must not decide"},
    )

    assert detail.status_code == 200
    assert detail.json()["status"] == "pending"
    assert detail.json()["client_id"] == "alpha"
    assert decision.status_code == 403
    assert decision.json()["detail"] == "insufficient role"


def test_live_execution_suite_requires_auth_and_returns_run_body(live_client, live_settings) -> None:
    """Live-fixture twin for execution reads with an explicit unauthenticated negative."""

    store = Store(live_settings.data_path)
    ensure_test_clients(store, "alpha")
    now = utc_now()
    run = store.create_execution_run("workflow", 17, "live-test", "completed", now, now, "test", client_id="alpha")

    missing = live_client.get("/executions")
    live_client.set_authorization("test-viewer-token")
    listed = live_client.get("/executions")

    assert missing.status_code == 401
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == run.id
    assert listed.json()[0]["status"] == "completed"


def test_live_audit_suite_returns_events_and_rejects_viewer_export(live_client, live_settings) -> None:
    """Live-fixture twin for audit export scope."""

    store = Store(live_settings.data_path)
    ensure_test_clients(store, "alpha")
    store.add_audit_event("live.audit", "subject-1", "body", client_id="alpha")
    live_client.set_authorization("test-viewer-token")

    events = live_client.get("/audit")
    export = live_client.get("/audit-events/export")

    assert events.status_code == 200
    assert events.json()[0]["event_type"] == "live.audit"
    assert events.json()[0]["client_id"] == "alpha"
    assert export.status_code == 403
    assert export.json()["detail"] == "insufficient role"


def test_live_secrets_suite_allows_admin_read_and_rejects_viewer(live_client) -> None:
    """Live-fixture twin for secrets: the response is never reached through demo auth."""

    live_client.set_authorization("test-viewer-token")
    viewer = live_client.get("/secrets")
    live_client.set_authorization("test-admin-token")
    admin = live_client.get("/secrets")

    assert viewer.status_code == 403
    assert viewer.json()["detail"] == "insufficient role"
    assert admin.status_code == 200
    assert any(item["key"] == "WAIT_HALOPSA_BASE_URL" for item in admin.json())


def test_live_principal_suite_allows_admin_management_and_rejects_viewer(live_client) -> None:
    """Live-fixture twin for principal/auth routes."""

    live_client.set_authorization("test-viewer-token")
    viewer = live_client.get("/auth/principals")
    live_client.set_authorization("test-admin-token")
    created = live_client.post(
        "/auth/principals",
        json={"principal_id": "live-principal", "kind": "staff", "display_name": "Live Principal"},
    )

    assert viewer.status_code == 403
    assert viewer.json()["detail"] == "insufficient role"
    assert created.status_code == 200
    assert created.json()["principal_id"] == "live-principal"
    assert created.json()["credentials"] == []


def test_live_client_scope_suite_exposes_bootstrap_scope_and_auth_boundary(live_client, live_settings) -> None:
    """Live-fixture twin for client scope enforcement."""

    store = Store(live_settings.data_path)
    ensure_test_clients(store, "alpha", "beta")
    live_client.set_authorization("test-viewer-token")

    beta = live_client.get("/clients", params={"client_id": "beta"})
    live_client.set_authorization(None)
    missing = live_client.get("/clients", params={"client_id": "beta"})

    assert beta.status_code == 200
    assert beta.json()[0]["client_id"] == "beta"
    assert missing.status_code == 401
    assert missing.json()["detail"] == "missing bearer token"


def test_live_backup_suite_returns_admin_status_and_rejects_viewer(live_client) -> None:
    """Live-fixture twin for backup lifecycle authorization."""

    live_client.set_authorization("test-viewer-token")
    viewer = live_client.get("/backups")
    live_client.set_authorization("test-admin-token")
    admin = live_client.get("/backups")

    assert viewer.status_code == 403
    assert viewer.json()["detail"] == "insufficient role"
    assert admin.status_code == 200
    assert admin.json()["items"] == []
    assert admin.json()["total"] == 0


def test_live_diagnostics_suite_returns_summary_and_rejects_viewer(live_client) -> None:
    """Live-fixture twin for diagnostics authorization and response shape."""

    live_client.set_authorization("test-viewer-token")
    viewer = live_client.get("/diagnostics/summary")
    live_client.set_authorization("test-admin-token")
    admin = live_client.get("/diagnostics/summary")

    assert viewer.status_code == 403
    assert viewer.json()["detail"] == "insufficient role"
    assert admin.status_code == 200
    assert admin.json()["database"]["integrity_check"] == "ok"
    assert admin.json()["support_upload"]["available"] is False


def test_live_core_connector_reads_honor_bound_scope(live_settings, monkeypatch) -> None:
    """Core provider reads must select a client instance before calling a provider."""

    class FakeM365GraphClient:
        def __init__(self, _settings, **kwargs) -> None:
            self.client_id = kwargs.get("client_id")

        def list_users(self, **_kwargs):
            client_id = self.client_id or "alpha,beta"
            return M365GraphReadResponse(
                ConnectorReadResult("ready", "fake", 1),
                [M365GraphUser("user-1", client_id, f"{client_id}@example.test", "", True, "", "")],
            )

    class FakeTokenProvider:
        configured = True

        def get_token(self) -> str:
            return "fake-token"

    class FakeM365Resolver:
        unavailable = False

        def __init__(self, _settings, _store, _vault) -> None:
            pass

        def resolve(self, client_id=None, *, allow_msp_wide=False):
            if self.unavailable or (client_id and client_id != "alpha"):
                raise M365ProfileResolutionError("no active client-scoped connector")
            return M365Connection("https://graph.microsoft.com/v1.0", FakeTokenProvider())

    class FakeConnectWiseClient:
        def __init__(self, _settings, **_kwargs) -> None:
            self.client_id = None

        def list_companies(self, **_kwargs):
            return ConnectWiseReadResponse(ConnectorReadResult("ready", "fake", 1), [{"name": self.client_id or "all"}])

    class FakeAutotaskClient:
        def __init__(self, _settings, **_kwargs) -> None:
            self.client_id = None

        def list_tickets(self, **_kwargs):
            return AutotaskReadResponse(ConnectorReadResult("ready", "fake", 1), [{"title": self.client_id or "all"}])

    monkeypatch.setattr(app_module, "M365GraphClient", FakeM365GraphClient)
    monkeypatch.setattr(scopes_module, "M365GraphClient", FakeM365GraphClient)
    monkeypatch.setattr(app_module, "M365ConnectionResolver", FakeM365Resolver)

    factory_unavailable = [False]

    def fake_client_factory(_store, connector_type, client_id, **_kwargs):
        if factory_unavailable[0]:
            raise ConnectorFactoryError("not configured")
        if connector_type == "connectwise":
            client: Any = FakeConnectWiseClient(None)
        elif connector_type == "autotask":
            client = FakeAutotaskClient(None)
        else:
            raise ConnectorFactoryError("not configured")
        client.client_id = client_id
        return client

    monkeypatch.setattr(app_module, "build_read_client_for_client", fake_client_factory)
    monkeypatch.setattr(scopes_module, "build_read_client_for_client", fake_client_factory)
    app = app_module.create_app(live_settings)
    store = Store(live_settings.data_path)
    ensure_test_clients(store, "alpha", "beta")
    store.create_principal("bound-viewer", kind="staff")
    store.add_principal_credential("bound-viewer", "bound-viewer-secret")
    store.add_principal_client_role("bound-viewer", "alpha", "viewer")
    bound_context = app_module.resolve_auth_context(live_settings, "Bearer bound-viewer-secret", app.state.store)
    msp_context = app_module.resolve_auth_context(live_settings, "Bearer test-admin-token", app.state.store)

    def request_for(path: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "headers": [],
                "app": app,
            }
        )

    def endpoint_for(path: str) -> Any:
        return next(route.endpoint for route in app.routes if isinstance(route, APIRoute) and route.path == path)

    m365 = endpoint_for("/connectors/m365/users")(
        request=request_for("/connectors/m365/users"),
        context=bound_context,
        identity=None,
        cursor=None,
        page_size=None,
        client_id=None,
    )
    connectwise = endpoint_for("/connectors/connectwise/companies")(
        request=request_for("/connectors/connectwise/companies"),
        context=bound_context,
        page=1,
        page_size=None,
        conditions=None,
        client_id=None,
    )
    autotask = endpoint_for("/connectors/autotask/tickets")(
        request=request_for("/connectors/autotask/tickets"),
        context=bound_context,
        page=1,
        page_size=None,
        client_id=None,
    )
    assert m365["items"][0]["display_name"] == "alpha"
    assert connectwise["items"] == [{"name": "alpha"}]
    assert autotask["items"] == [{"title": "alpha"}]

    with pytest.raises(HTTPException) as foreign:
        endpoint_for("/connectors/m365/users")(
            request=request_for("/connectors/m365/users"),
            context=bound_context,
            identity=None,
            cursor=None,
            page_size=None,
            client_id="beta",
        )
    assert foreign.value.status_code == 403
    with pytest.raises(HTTPException) as halo:
        endpoint_for("/connectors/halopsa/tickets")(
            request=request_for("/connectors/halopsa/tickets"),
            context=bound_context,
            page=1,
            page_size=50,
            client_id=None,
        )
    assert halo.value.status_code == 409
    assert halo.value.detail == {"code": "client_scope_unsupported"}
    msp = endpoint_for("/connectors/m365/users")(
        request=request_for("/connectors/m365/users"),
        context=msp_context,
        identity=None,
        cursor=None,
        page_size=None,
        client_id=None,
    )
    assert msp["items"][0]["display_name"] == "alpha,beta"

    teams = endpoint_for("/connectors/m365/teams")(
        request=request_for("/connectors/m365/teams"),
        context=bound_context,
        client_id=None,
    )
    assert teams["result"]["status"] == "blocked"
    with pytest.raises(HTTPException) as unsupported:
        endpoint_for("/connectors/confluence/pages")(
            request=request_for("/connectors/confluence/pages"),
            context=bound_context,
            space_id=None,
            title=None,
            cursor=None,
            page_size=None,
            client_id=None,
        )
    assert unsupported.value.status_code == 409
    assert unsupported.value.detail == {"code": "client_scope_unsupported"}

    FakeM365Resolver.unavailable = True
    with pytest.raises(HTTPException) as unavailable:
        endpoint_for("/connectors/m365/users")(
            request=request_for("/connectors/m365/users"),
            context=bound_context,
            identity=None,
            cursor=None,
            page_size=None,
            client_id=None,
        )
    factory_unavailable[0] = True
    with pytest.raises(HTTPException) as psa_unavailable:
        endpoint_for("/connectors/connectwise/companies")(
            request=request_for("/connectors/connectwise/companies"),
            context=bound_context,
            page=1,
            page_size=None,
            conditions=None,
            client_id=None,
        )
    assert unavailable.value.status_code == 409
    assert unavailable.value.detail == {"code": "client_scope_unavailable", "client_id": "alpha"}
    assert psa_unavailable.value.status_code == 409
    assert psa_unavailable.value.detail == {"code": "client_scope_unavailable", "client_id": "alpha"}


def test_live_core_connector_factory_selects_real_client_scope(live_settings) -> None:
    """The API must exercise persisted instance selection, not a factory stub."""
    settings = live_settings.__class__(
        **{
            **live_settings.__dict__,
            "allow_http_probing": True,
            "connector_instance_allowed_hosts": ("1.1.1.1", "8.8.8.8"),
        }
    )
    store = Store(settings.data_path)
    ensure_test_clients(store, "alpha", "beta")
    vault = SecretVault.initialize(settings.vault_path, demo_mode=True)
    credential = json.dumps(
        {
            "company": "instance-company",
            "public_key": "instance-public",
            "private_key": "instance-private",
            "client_id": "instance-client",
        }
    )
    vault.set("alpha-connectwise", credential)
    vault.set("beta-connectwise", credential)
    alpha = store.create_connector_instance(
        "connectwise",
        "Alpha ConnectWise",
        client_id="alpha",
        credential_ref="alpha-connectwise",
        config_json=json.dumps({"base_url": "https://1.1.1.1"}),
    )
    beta = store.create_connector_instance(
        "connectwise",
        "Beta ConnectWise",
        client_id="beta",
        credential_ref="beta-connectwise",
        config_json=json.dumps({"base_url": "https://8.8.8.8"}),
    )
    assert store.update_connector_instance(alpha.connector_instance_id, status="active") is not None
    assert store.update_connector_instance(beta.connector_instance_id, status="active") is not None

    def provider_handler(request: httpx.Request) -> httpx.Response:
        rows = {
            "1.1.1.1": {"id": "alpha-company", "name": "Alpha company"},
            "8.8.8.8": {"id": "beta-company", "name": "Beta company"},
        }
        host = request.url.host
        assert host is not None
        return httpx.Response(200, json=[rows[host]])

    transport = httpx.MockTransport(provider_handler)
    store.create_principal("bound-viewer", kind="staff")
    store.add_principal_credential("bound-viewer", "bound-viewer-secret")
    store.add_principal_client_role("bound-viewer", "alpha", "viewer")
    app = app_module.create_app(settings)
    app.state.connectwise_transport = transport
    context = resolve_auth_context(settings, "Bearer bound-viewer-secret", app.state.store)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/connectors/connectwise/companies"
    )

    def read(client_id: str | None = None) -> dict[str, object]:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/connectors/connectwise/companies",
                "headers": [],
                "app": app,
            }
        )
        return endpoint(
            request=request,
            context=context,
            page=1,
            page_size=None,
            conditions=None,
            client_id=client_id,
        )

    alpha_response = read()
    try:
        read("beta")
    except HTTPException as foreign_response:
        assert foreign_response.status_code == 403
    else:  # pragma: no cover - the scope gate must reject the request
        raise AssertionError("foreign client scope was accepted")
    assert alpha_response["items"] == [
        {"id": "alpha-company", "name": "Alpha company", "status": ""}
    ]

    assert store.update_connector_instance(alpha.connector_instance_id, status="inactive") is not None
    with pytest.raises(HTTPException) as unavailable:
        read()
    assert unavailable.value.status_code == 409
    assert unavailable.value.detail == {"code": "client_scope_unavailable", "client_id": "alpha"}

    replacement = store.create_connector_instance(
        "connectwise",
        "Alpha ConnectWise replacement",
        client_id="alpha",
        credential_ref="alpha-connectwise",
        config_json=json.dumps({"base_url": "https://1.1.1.1"}),
    )
    assert store.update_connector_instance(replacement.connector_instance_id, status="active") is not None
    second = store.create_connector_instance(
        "connectwise",
        "Alpha ConnectWise second",
        client_id="alpha",
        credential_ref="alpha-connectwise",
        config_json=json.dumps({"base_url": "https://1.1.1.1"}),
    )
    assert store.update_connector_instance(second.connector_instance_id, status="active") is not None
    with pytest.raises(HTTPException) as ambiguous:
        read()
    assert ambiguous.value.status_code == 409
    assert ambiguous.value.detail == {"code": "client_scope_unavailable", "client_id": "alpha"}
