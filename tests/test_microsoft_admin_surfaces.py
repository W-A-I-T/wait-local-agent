from __future__ import annotations

import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from packs.microsoft_admin.cli import app as microsoft_admin_cli
from packs.microsoft_admin.core import MicrosoftAdminError
from packs.microsoft_admin.router import create_router
from microsoft_admin_support import _configured
from wait_local_agent.models import ConnectorReadResult


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
