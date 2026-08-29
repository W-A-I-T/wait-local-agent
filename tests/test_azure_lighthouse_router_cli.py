from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import packs.azure_lighthouse as lighthouse_package
from packs.azure_lighthouse.cli import app as lighthouse_cli
from packs.azure_lighthouse.models import (
    AzureLighthouseAuthorizationError,
    AzureLighthouseBlockedError,
    AzureLighthouseCredentialError,
    AzureLighthouseProviderError,
    AzureLighthouseValidationError,
)
from packs.azure_lighthouse.router import create_router
from tests.azure_lighthouse_support import (
    CUSTOMER_TENANT_ID,
    MANAGING_TENANT_ID,
    PRINCIPAL_ID,
    SUBSCRIPTION_ID,
    FakeCredential,
    assignment_payload,
    configured_settings,
    resource_payload,
    subscription_payload,
)


class AuditStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, str | None]] = []

    def add_audit_event(
        self,
        event_type: str,
        entity_id: str,
        message: str,
        *,
        client_id: str | None = None,
    ) -> None:
        self.events.append((event_type, entity_id, message, client_id))


def make_app(settings, transport: httpx.BaseTransport, store: AuditStore | None = None) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.store = store or AuditStore()
    app.state.azure_lighthouse_transport = transport
    app.state.azure_lighthouse_credential_factory = (
        lambda active_settings, credential_ref, managing_tenant_id: FakeCredential()
    )
    app.include_router(create_router(), prefix="/packs/azure-lighthouse")
    return app


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/subscriptions":
        return httpx.Response(200, json={"value": [subscription_payload()]})
    if request.url.path.endswith("/registrationAssignments"):
        return httpx.Response(200, json={"value": [assignment_payload()]})
    if request.url.path.endswith("/resources"):
        return httpx.Response(200, json={"value": [resource_payload()]})
    raise AssertionError(request.url)


def connection_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "client_id": "client-contoso",
        "credential_ref": "cloud/lighthouse",
        "managing_tenant_id": MANAGING_TENANT_ID,
        "expected_customer_tenant_id": CUSTOMER_TENANT_ID,
    }
    payload.update(overrides)
    return payload


def test_lighthouse_is_integrated_without_creating_a_second_pack_boundary() -> None:
    assert not hasattr(lighthouse_package, "PACK_MANIFEST")


def test_router_discovers_inventories_generates_onboarding_and_audits(settings, tmp_path: Path) -> None:
    store = AuditStore()
    app = make_app(
        configured_settings(settings, tmp_path),
        httpx.MockTransport(handler),
        store,
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-token"}

    status = client.get("/packs/azure-lighthouse/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["read_only"] is True
    assert status.json()["customer_onboarding_deployed_by_wait"] is False

    discover = client.post(
        "/packs/azure-lighthouse/discover",
        headers=headers,
        json=connection_payload(),
    )
    assert discover.status_code == 200
    assert discover.json()["subscriptions"][0]["verification_status"] == "verified"

    inventory = client.post(
        "/packs/azure-lighthouse/inventory",
        headers=headers,
        json=connection_payload(subscription_id=SUBSCRIPTION_ID, resource_group=None, limit=25),
    )
    assert inventory.status_code == 200
    assert inventory.json()["delegation_verified"] is True
    assert inventory.json()["resources"][0]["name"] == "app-vm"

    onboarding = client.post(
        "/packs/azure-lighthouse/onboarding/plan",
        headers=headers,
        json={
            "client_id": "client-contoso",
            "offer_name": "WAIT delegated inventory",
            "offer_description": "Read-only Azure inventory.",
            "managing_tenant_id": MANAGING_TENANT_ID,
            "principal_id": PRINCIPAL_ID,
            "principal_display_name": "WAIT Local Agent",
            "deployment_scope": "subscription",
        },
    )
    assert onboarding.status_code == 200
    assert onboarding.json()["role_profile"] == "inventory-reader"
    assert onboarding.json()["bundle_sha256"].startswith("sha256:")

    assert [event[0] for event in store.events] == [
        "azure_lighthouse.delegations_discovered",
        "azure_lighthouse.inventory_collected",
        "azure_lighthouse.onboarding_plan_generated",
    ]
    assert all(event[3] == "client-contoso" for event in store.events)


def test_router_requires_admin_and_one_explicit_client(settings, tmp_path: Path) -> None:
    client = TestClient(
        make_app(configured_settings(settings, tmp_path), httpx.MockTransport(handler))
    )
    for token in ("viewer-token", "tech-token"):
        response = client.post(
            "/packs/azure-lighthouse/discover",
            headers={"Authorization": f"Bearer {token}"},
            json=connection_payload(),
        )
        assert response.status_code == 403

    missing_client = client.post(
        "/packs/azure-lighthouse/discover",
        headers={"Authorization": "Bearer admin-token"},
        json=connection_payload(client_id=None),
    )
    assert missing_client.status_code == 403
    assert "client" in missing_client.json()["detail"].casefold()


def test_router_maps_all_sanitized_error_classes(settings, tmp_path: Path) -> None:
    configured = configured_settings(settings, tmp_path)
    error_cases = [
        (AzureLighthouseBlockedError("blocked"), 403),
        (AzureLighthouseCredentialError("credential"), 400),
        (AzureLighthouseValidationError("validation"), 422),
        (AzureLighthouseAuthorizationError("authorization"), 403),
        (AzureLighthouseProviderError("provider"), 502),
        (RuntimeError("internal-secret"), 500),
    ]
    for error, expected_status in error_cases:
        app = make_app(configured, httpx.MockTransport(handler))
        app.state.azure_lighthouse_credential_factory = (
            lambda active_settings, credential_ref, managing_tenant_id, exc=error: (_ for _ in ()).throw(exc)
        )
        response = TestClient(app).post(
            "/packs/azure-lighthouse/discover",
            headers={"Authorization": "Bearer admin-token"},
            json=connection_payload(),
        )
        assert response.status_code == expected_status
        if expected_status == 500:
            assert "internal-secret" not in response.text


def test_router_status_reflects_blocked_policy_and_validates_onboarding(settings, tmp_path: Path) -> None:
    blocked_settings = replace(configured_settings(settings, tmp_path), allow_http_probing=False)
    client = TestClient(make_app(blocked_settings, httpx.MockTransport(handler)))
    headers = {"Authorization": "Bearer admin-token"}
    assert client.get("/packs/azure-lighthouse/status", headers=headers).json()["status"] == "blocked"

    invalid = client.post(
        "/packs/azure-lighthouse/onboarding/plan",
        headers=headers,
        json={
            "client_id": "client-contoso",
            "offer_name": "WAIT",
            "offer_description": "Reader.",
            "managing_tenant_id": MANAGING_TENANT_ID,
            "principal_id": PRINCIPAL_ID,
            "principal_display_name": "WAIT",
            "deployment_scope": "resource_group",
        },
    )
    assert invalid.status_code == 200

    malformed = client.post(
        "/packs/azure-lighthouse/onboarding/plan",
        headers=headers,
        json={
            "client_id": "client-contoso",
            "offer_name": "WAIT",
            "offer_description": "Reader.",
            "managing_tenant_id": "not-a-guid-not-a-guid-not-a-guid-xx",
            "principal_id": PRINCIPAL_ID,
            "principal_display_name": "WAIT",
            "deployment_scope": "subscription",
        },
    )
    assert malformed.status_code in {422}


def test_cli_status_discover_inventory_and_onboarding(monkeypatch) -> None:
    import packs.azure_lighthouse.cli as cli_module

    settings = SimpleNamespace(allow_http_probing=True)

    class FakeClient:
        def __init__(self, active_settings, credential) -> None:
            self.active_settings = active_settings
            self.credential = credential

        def discover(self, **kwargs):
            return SimpleNamespace(to_dict=lambda: {"status": "ready", "subscriptions": []})

        def inventory(self, **kwargs):
            return SimpleNamespace(to_dict=lambda: {"status": "ready", "resources": []})

    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "credential_from_vault", lambda *args: FakeCredential())
    monkeypatch.setattr(cli_module, "AzureLighthouseClient", FakeClient)

    runner = CliRunner()
    status = runner.invoke(lighthouse_cli, ["status"])
    discover = runner.invoke(
        lighthouse_cli,
        [
            "discover",
            "--credential-ref", "cloud/lighthouse",
            "--managing-tenant", MANAGING_TENANT_ID,
            "--customer-tenant", CUSTOMER_TENANT_ID,
            "--client", "client-contoso",
        ],
    )
    inventory = runner.invoke(
        lighthouse_cli,
        [
            "inventory",
            "--credential-ref", "cloud/lighthouse",
            "--managing-tenant", MANAGING_TENANT_ID,
            "--customer-tenant", CUSTOMER_TENANT_ID,
            "--subscription", SUBSCRIPTION_ID,
            "--client", "client-contoso",
            "--resource-group", "app-rg",
            "--limit", "10",
        ],
    )
    onboarding = runner.invoke(
        lighthouse_cli,
        [
            "onboarding-plan",
            "--offer-name", "WAIT",
            "--description", "Reader inventory.",
            "--managing-tenant", MANAGING_TENANT_ID,
            "--principal", PRINCIPAL_ID,
            "--principal-name", "WAIT Local Agent",
            "--scope", "resource_group",
        ],
    )

    assert status.exit_code == 0
    assert json.loads(status.output)["read_only"] is True
    assert discover.exit_code == 0
    assert json.loads(discover.output)["status"] == "ready"
    assert inventory.exit_code == 0
    assert json.loads(inventory.output)["status"] == "ready"
    assert onboarding.exit_code == 0
    assert json.loads(onboarding.output)["role_profile"] == "inventory-reader"


def test_cli_returns_exit_two_for_provider_and_onboarding_errors(monkeypatch) -> None:
    import packs.azure_lighthouse.cli as cli_module

    monkeypatch.setattr(cli_module, "load_settings", lambda: SimpleNamespace(allow_http_probing=True))
    monkeypatch.setattr(
        cli_module,
        "credential_from_vault",
        lambda *args: (_ for _ in ()).throw(AzureLighthouseCredentialError("credential unavailable")),
    )
    runner = CliRunner()
    failed = runner.invoke(
        lighthouse_cli,
        [
            "discover",
            "--credential-ref", "missing",
            "--managing-tenant", MANAGING_TENANT_ID,
            "--customer-tenant", CUSTOMER_TENANT_ID,
            "--client", "client-contoso",
        ],
    )
    invalid_scope = runner.invoke(
        lighthouse_cli,
        [
            "onboarding-plan",
            "--offer-name", "WAIT",
            "--description", "Reader.",
            "--managing-tenant", MANAGING_TENANT_ID,
            "--principal", PRINCIPAL_ID,
            "--principal-name", "WAIT",
            "--scope", "tenant",
        ],
    )
    assert failed.exit_code == 2
    assert "credential unavailable" in failed.output
    assert invalid_scope.exit_code == 2
    assert "subscription or resource_group" in invalid_scope.output
