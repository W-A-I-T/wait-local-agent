from __future__ import annotations

from tests.support import ensure_test_clients
from wait_local_agent.models import utc_now
from wait_local_agent.store import Store


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
