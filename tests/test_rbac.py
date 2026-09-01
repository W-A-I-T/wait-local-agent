from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.support import ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.capabilities import MICROSOFT_ADMIN_CAPABILITY, grant_capability
from wait_local_agent.rbac import (
    AuthContext,
    Role,
    _role_from_label,
    _session_expired,
    require_capability,
    require_capability_scope,
    resolve_auth_context,
)
from wait_local_agent.sessions import hash_session_token, session_expiries
from wait_local_agent.store import AuthSessionRecord, Store


def test_auth_role_endpoint_reports_rbac_roles_and_legacy_api_token(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "api_token": "legacy-admin",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "client_id": "acme",
        }
    )
    client = TestClient(create_app(secure_settings))

    viewer = client.get("/auth/role", headers=_auth("viewer-token"))
    technician = client.get("/auth/role", headers=_auth("tech-token"))
    admin = client.get("/auth/role", headers=_auth("admin-token"))
    legacy = client.get("/auth/role", headers=_auth("legacy-admin"))

    assert viewer.status_code == 200
    assert viewer.json()["role"] == "viewer"
    assert technician.status_code == 200
    assert technician.json()["role"] == "technician"
    assert technician.json()["client_id"] == "acme"
    assert admin.status_code == 200
    assert admin.json()["role"] == "admin"
    assert legacy.status_code == 200
    assert legacy.json()["role"] == "admin"


def test_auth_role_endpoint_reports_end_user_support_setting(settings) -> None:
    for enabled in (False, True):
        client = TestClient(create_app(replace(settings, end_user_support_enabled=enabled)))

        response = client.get("/auth/role")

        assert response.status_code == 200
        assert response.json()["end_user_support_enabled"] is enabled


def test_route_enforcement_matches_rbac_contract(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    approval = store.create_approval_request(
        "TCK-1001",
        "ticket.assign",
        {"ticket_id": "TCK-1001"},
        client_id="acme",
    )
    client = TestClient(create_app(secure_settings))

    viewer_approval = client.post(
        f"/approval-requests/{approval.id}",
        headers=_auth("viewer-token"),
        json={"status": "approved", "comment": "nope"},
    )
    viewer_workflow = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        headers=_auth("viewer-token"),
        json={"ticket_id": "TCK-1001"},
    )
    technician_approval = client.post(
        f"/approval-requests/{approval.id}",
        headers=_auth("tech-token"),
        json={"status": "approved", "comment": "approved"},
    )
    technician_secrets = client.get("/secrets", headers=_auth("tech-token"))
    technician_export = client.get("/audit-events/export", headers=_auth("tech-token"))
    admin_secrets = client.get("/secrets", headers=_auth("admin-token"))
    admin_export = client.get("/audit-events/export", headers=_auth("admin-token"))

    assert viewer_approval.status_code == 403
    assert viewer_workflow.status_code == 403
    assert technician_approval.status_code == 200
    assert technician_secrets.status_code == 403
    assert technician_export.status_code == 403
    assert admin_secrets.status_code == 200
    assert admin_export.status_code == 200


def test_demo_mode_with_no_tokens_preserves_existing_access(settings) -> None:
    client = TestClient(create_app(settings))

    health = client.get("/health")
    secrets = client.get("/secrets")
    export = client.get("/audit-events/export")

    assert health.status_code == 200
    assert secrets.status_code == 403
    assert export.status_code == 200


def test_auth_context_resolves_install_tenant_for_demo_and_tokens(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "client_id": " acme ",
            "demo_mode": False,
            "tech_token": "tech-token",
        }
    )

    technician = resolve_auth_context(secure_settings, "Bearer tech-token")
    demo = resolve_auth_context(
        secure_settings.__class__(**{**secure_settings.__dict__, "demo_mode": True}),
        None,
    )

    assert technician.role == Role.TECHNICIAN
    assert technician.client_id == "acme"
    assert demo.role == Role.ADMIN
    assert demo.client_id == "acme"


def test_cookie_session_uses_principal_scope_and_requires_csrf_for_writes(settings) -> None:
    secure_settings = replace(settings, demo_mode=False, client_id="acme")
    store = Store(secure_settings.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_client_role("operator", "acme", "technician")
    raw_token = "opaque-session"
    idle, absolute = session_expiries()
    store.create_auth_session(
        hash_session_token(raw_token),
        "operator",
        idle_expires_at=idle,
        absolute_expires_at=absolute,
    )

    context = resolve_auth_context(
        secure_settings,
        None,
        store,
        session_token=raw_token,
        request_method="GET",
    )

    assert context.role == Role.TECHNICIAN
    assert context.client_id == "acme"
    assert context.auth_method == "local"
    assert context.approver_id == "operator"
    with pytest.raises(HTTPException) as exc_info:
        resolve_auth_context(
            secure_settings,
            None,
            store,
            session_token=raw_token,
            request_method="POST",
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"code": "csrf_required"}


def test_bearer_header_precedes_cookie_session(settings) -> None:
    secure_settings = replace(settings, demo_mode=False, viewer_token="viewer-token")
    store = Store(secure_settings.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_client_role("operator", "acme", "admin")
    raw_token = "opaque-session"
    idle, absolute = session_expiries()
    store.create_auth_session(
        hash_session_token(raw_token),
        "operator",
        idle_expires_at=idle,
        absolute_expires_at=absolute,
    )

    context = resolve_auth_context(
        secure_settings,
        "Bearer viewer-token",
        store,
        session_token=raw_token,
        request_method="POST",
    )

    assert context.role == Role.VIEWER
    assert context.auth_method == "bearer"


def test_session_expiry_edges_and_revocation_fail_closed(settings) -> None:
    secured = replace(settings, demo_mode=False, client_id="acme")
    store = Store(secured.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_client_role("operator", "acme", "admin")

    for token, idle, absolute, revoke in (
        ("idle-expired", "2000-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00", False),
        ("absolute-expired", "2999-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", False),
        ("revoked", "2999-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00", True),
    ):
        session_hash = hash_session_token(token)
        store.create_auth_session(
            session_hash,
            "operator",
            idle_expires_at=idle,
            absolute_expires_at=absolute,
        )
        if revoke:
            assert store.revoke_auth_session(session_hash) is True
        with pytest.raises(HTTPException, match="invalid session"):
            resolve_auth_context(secured, None, store, session_token=token, request_method="GET")

    with pytest.raises(HTTPException, match="invalid session"):
        resolve_auth_context(secured, None, store, session_token="malformed-cookie", request_method="GET")


def test_session_expiry_checks_idle_and_absolute_deadlines() -> None:
    def record(idle_expires_at: str, absolute_expires_at: str) -> AuthSessionRecord:
        return AuthSessionRecord(
            session_token_hash="hash",
            principal_id="operator",
            auth_method="local",
            created_at="2026-01-01T00:00:00+00:00",
            last_seen_at="2026-01-01T00:00:00+00:00",
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            revoked=False,
            user_agent="",
        )

    assert _session_expired(record("2000-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00")) is True
    assert _session_expired(record("2999-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00")) is True
    assert _session_expired(record("2999-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00")) is False


def test_local_principal_resolution_uses_settings_store_fallback(settings) -> None:
    secured = replace(settings, demo_mode=False, client_id="acme")
    store = Store(secured.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_credential("operator", "operator-secret")
    store.add_principal_client_role("operator", "acme", "admin")

    context = resolve_auth_context(secured, "Bearer operator-secret")

    assert context.principal_id == "operator"
    assert context.role == Role.ADMIN


def test_invalid_principal_role_is_rejected() -> None:
    with pytest.raises(HTTPException, match="invalid role"):
        _role_from_label("not-a-role")


def test_capability_dependency_and_scope_enforce_selected_client(settings) -> None:
    secured = replace(settings, demo_mode=False, client_id="acme")
    store = Store(secured.data_path)
    store.create_client('acme', 'Acme')
    store.create_principal("operator", kind="staff")
    store.add_principal_credential("operator", "operator-secret")
    store.add_principal_client_role("operator", "acme", "admin")
    grant_capability(
        store,
        principal_id="operator",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id="acme",
        actor_id="bootstrap",
    )
    app = SimpleNamespace(state=SimpleNamespace(settings=secured, store=store))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )

    context = require_capability(MICROSOFT_ADMIN_CAPABILITY)(
        request, authorization="Bearer operator-secret", selected_client_id="acme"
    )

    assert context.principal_id == "operator"
    assert require_capability_scope(context, MICROSOFT_ADMIN_CAPABILITY, "acme") == "acme"
    with pytest.raises(HTTPException, match="client_scope_mismatch"):
        require_capability_scope(context, MICROSOFT_ADMIN_CAPABILITY, "other")


def test_capability_failure_reasons_cover_missing_principal_and_grant(settings) -> None:
    no_principal = AuthContext(role=Role.ADMIN, presented_token="bootstrap", is_msp_admin=True)
    with pytest.raises(HTTPException) as bootstrap_error:
        require_capability_scope(no_principal, MICROSOFT_ADMIN_CAPABILITY, "acme")
    assert bootstrap_error.value.detail["reason"] == "no_principal"

    no_grant = AuthContext(
        role=Role.ADMIN,
        presented_token=None,
        principal_id="operator",
        client_id="acme",
        client_ids=frozenset({"acme"}),
    )
    with pytest.raises(HTTPException) as grant_error:
        require_capability_scope(no_grant, MICROSOFT_ADMIN_CAPABILITY, "acme")
    assert grant_error.value.detail["reason"] == "no_grant"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
