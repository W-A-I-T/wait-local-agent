from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def test_auth_role_endpoint_reports_rbac_roles_and_legacy_api_token(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "api_token": "legacy-admin",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
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
    assert admin.status_code == 200
    assert admin.json()["role"] == "admin"
    assert legacy.status_code == 200
    assert legacy.json()["role"] == "admin"


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
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
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
    assert secrets.status_code == 200
    assert export.status_code == 200


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
