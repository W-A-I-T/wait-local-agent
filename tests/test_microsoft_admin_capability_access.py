from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from packs.microsoft_admin.runbooks import create_runbook_approval
from wait_local_agent.api.app import create_app
from wait_local_agent.capabilities import MICROSOFT_ADMIN_CAPABILITY, grant_capability
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _secure_settings(settings):
    return replace(
        settings,
        demo_mode=False,
        admin_token="bootstrap-admin",
        client_id="alpha",
    )


def _seed_staff(
    store: Store,
    principal_id: str,
    token: str,
    role: str,
    *,
    clients: tuple[str, ...] = ("alpha", "beta"),
    msp_admin: bool = False,
) -> None:
    store.create_principal(principal_id, kind="staff", display_name=principal_id)
    store.add_principal_credential(principal_id, token)
    for client_id in clients:
        store.add_principal_client_role(principal_id, client_id, role)
    if msp_admin:
        store.add_principal_global_role(principal_id)


def test_microsoft_admin_is_default_deny_and_grant_takes_effect_next_request(settings) -> None:
    secure = _secure_settings(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _seed_staff(store, "viewer-ab", "viewer-ab-secret", "viewer")
    client = TestClient(create_app(secure))

    bootstrap_denied = client.get(
        "/packs/microsoft-admin/runbooks?client_id=alpha",
        headers=_auth("bootstrap-admin"),
    )
    viewer_denied = client.get(
        "/packs/microsoft-admin/runbooks?client_id=alpha",
        headers=_auth("viewer-ab-secret"),
    )
    effective_before = client.get(
        "/packs/microsoft-admin/access/effective",
        headers=_auth("viewer-ab-secret"),
    )
    granted = client.post(
        "/packs/microsoft-admin/access/grants",
        headers=_auth("bootstrap-admin"),
        json={
            "principal_id": "viewer-ab",
            "capability_key": MICROSOFT_ADMIN_CAPABILITY,
            "client_id": "alpha",
        },
    )
    viewer_allowed = client.get(
        "/packs/microsoft-admin/runbooks?client_id=alpha",
        headers=_auth("viewer-ab-secret"),
    )
    viewer_beta_denied = client.get(
        "/packs/microsoft-admin/runbooks?client_id=beta",
        headers=_auth("viewer-ab-secret"),
    )
    effective_after = client.get(
        "/packs/microsoft-admin/access/effective",
        headers=_auth("viewer-ab-secret"),
    )

    assert bootstrap_denied.status_code == 403
    assert viewer_denied.status_code == 403
    assert effective_before.status_code == 200
    assert effective_before.json()["grants"] == []
    assert granted.status_code == 200
    assert granted.json()["active"] is True
    assert viewer_allowed.status_code == 200
    assert viewer_allowed.json()
    assert viewer_beta_denied.status_code == 403
    assert viewer_beta_denied.json()["detail"] == {
        "code": "capability_required",
        "capability": MICROSOFT_ADMIN_CAPABILITY,
        "reason": "client_scope_mismatch",
        "remediation": (
            "Use a client covered by this principal's microsoft_admin grant or add a grant for the requested client."
        ),
    }
    assert effective_after.json()["grants"] == [
        {"capability_key": MICROSOFT_ADMIN_CAPABILITY, "client_id": "alpha"}
    ]

    revoked = client.post(
        "/packs/microsoft-admin/access/grants/revoke",
        headers=_auth("bootstrap-admin"),
        json={
            "principal_id": "viewer-ab",
            "capability_key": MICROSOFT_ADMIN_CAPABILITY,
            "client_id": "alpha",
        },
    )
    denied_after_revoke = client.get(
        "/packs/microsoft-admin/runbooks?client_id=alpha",
        headers=_auth("viewer-ab-secret"),
    )

    assert revoked.status_code == 200
    assert revoked.json()["active"] is False
    assert denied_after_revoke.status_code == 403


def test_microsoft_admin_capability_denials_explain_bootstrap_and_missing_grants(settings) -> None:
    secure = _secure_settings(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    _seed_staff(store, "viewer-alpha", "viewer-alpha-secret", "viewer", clients=("alpha",))
    client = TestClient(create_app(secure))

    bootstrap_denied = client.get(
        "/packs/microsoft-admin/status?client_id=alpha",
        headers=_auth("bootstrap-admin"),
    )
    principal_denied = client.get(
        "/packs/microsoft-admin/status?client_id=alpha",
        headers=_auth("viewer-alpha-secret"),
    )

    assert bootstrap_denied.status_code == 403
    assert bootstrap_denied.json()["detail"]["reason"] == "no_principal"
    assert bootstrap_denied.json()["detail"]["code"] == "capability_required"
    assert principal_denied.status_code == 403
    assert principal_denied.json()["detail"]["reason"] == "no_grant"
    assert principal_denied.json()["detail"]["capability"] == MICROSOFT_ADMIN_CAPABILITY


def test_runbook_draft_rechecks_capability_for_payload_client(settings) -> None:
    secure = _secure_settings(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _seed_staff(store, "tech-ab", "tech-ab-secret", "technician")
    grant_capability(
        store,
        principal_id="tech-ab",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id="alpha",
        actor_id="bootstrap",
    )
    client = TestClient(create_app(secure))

    alpha_plan = client.post(
        "/packs/microsoft-admin/runbooks/plan",
        headers=_auth("tech-ab-secret"),
        json={"runbook_id": "windows.endpoint_health", "parameters": {}, "client_id": "alpha"},
    )
    beta_plan = client.post(
        "/packs/microsoft-admin/runbooks/plan",
        headers=_auth("tech-ab-secret"),
        json={"runbook_id": "windows.endpoint_health", "parameters": {}, "client_id": "beta"},
    )
    beta_draft = client.post(
        "/packs/microsoft-admin/runbooks/drafts",
        headers=_auth("tech-ab-secret"),
        json={"runbook_id": "windows.endpoint_health", "parameters": {}, "client_id": "beta"},
    )

    assert alpha_plan.status_code == 200
    assert beta_plan.status_code == 403
    assert beta_plan.json()["detail"]["reason"] == "client_scope_mismatch"
    assert beta_draft.status_code == 403


def test_runbook_execute_rechecks_capability_for_approval_client(settings) -> None:
    secure = _secure_settings(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _seed_staff(store, "admin-ab", "admin-ab-secret", "admin")
    grant_capability(
        store,
        principal_id="admin-ab",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id="alpha",
        actor_id="bootstrap",
    )
    approval, _ = create_runbook_approval(
        store,
        client_id="beta",
        runbook_id="windows.endpoint_health",
        parameters={},
    )
    client = TestClient(create_app(secure))

    response = client.post(
        f"/packs/microsoft-admin/runbooks/approvals/{approval.id}/execute",
        headers=_auth("admin-ab-secret"),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "client_scope_mismatch"


def test_access_management_requires_msp_operator_and_demo_is_read_only(settings) -> None:
    secure = _secure_settings(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    _seed_staff(store, "client-admin", "client-admin-secret", "admin", clients=("alpha",))
    _seed_staff(store, "viewer-alpha", "viewer-alpha-secret", "viewer", clients=("alpha",))
    client = TestClient(create_app(secure))

    denied = client.get(
        "/packs/microsoft-admin/access/principals",
        headers=_auth("client-admin-secret"),
    )
    principals = client.get(
        "/packs/microsoft-admin/access/principals",
        headers=_auth("bootstrap-admin"),
    )
    grants = client.get(
        "/packs/microsoft-admin/access/grants?capability_key=microsoft_admin",
        headers=_auth("bootstrap-admin"),
    )

    assert denied.status_code == 403
    assert principals.status_code == 200
    assert {row["principal_id"] for row in principals.json()} >= {"client-admin", "viewer-alpha"}
    assert grants.status_code == 200

    demo = TestClient(create_app(replace(settings, demo_mode=True, client_id="demo")))
    effective = demo.get("/packs/microsoft-admin/access/effective")
    demo_write = demo.post(
        "/packs/microsoft-admin/access/grants",
        json={
            "principal_id": "anything",
            "capability_key": MICROSOFT_ADMIN_CAPABILITY,
            "client_id": "demo",
        },
    )

    assert effective.status_code == 200
    assert effective.json()["grants"] == [
        {"capability_key": MICROSOFT_ADMIN_CAPABILITY, "client_id": "demo"}
    ]
    assert demo_write.status_code == 403
    assert demo_write.json()["detail"] == "capability grants cannot be changed in demo mode"
