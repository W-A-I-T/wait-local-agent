from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
import wait_local_agent.api.routers.system as system_module
from tests.support import ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def test_health_reports_safe_defaults(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["write_actions_enabled"] is False
    assert response.json()["http_probing_enabled"] is False
    assert response.json()["cloud_fallback_enabled"] is False
    assert response.json()["offline_mode"] is False
    assert response.json()["demo_mode"] is True
    assert response.json()["api_auth_required"] is False


def test_health_falls_back_to_static_m365_credentials_when_profile_resolution_fails(settings, monkeypatch) -> None:
    configured = replace(settings, m365_graph_base_url="https://graph.example.test", m365_access_token="token")

    def fail_resolution(*_args, **_kwargs):
        raise ValueError("ambiguous stored profile")

    monkeypatch.setattr(app_module.M365ConnectionResolver, "resolve", fail_resolution)
    application = create_app(configured)
    health_route = next(route for route in application.routes if getattr(route, "path", None) == "/health")
    assert isinstance(health_route, APIRoute)
    health = health_route.endpoint
    response = health(None, None)

    assert response["m365_configured"] is True


def test_provider_settings_and_tickets_list(settings) -> None:
    ingest_local(Store(settings.data_path), Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    providers = client.get("/settings/providers")
    tickets = client.get("/tickets")

    assert providers.status_code == 200
    assert providers.json()["vector_backend"] == "sqlite"
    assert providers.json()["llm_inference_enabled"] is False
    assert providers.json()["local_model_timeout_seconds"] == 20.0
    assert providers.json()["provider_scope"] == "appliance-wide"
    assert providers.json()["context_scope"] == "tenant-scoped"
    assert providers.json()["offline_mode"] is False
    assert providers.json()["remote_model_enabled"] is False
    assert providers.json()["model_input_cost_usd_per_million_tokens"] is None
    assert providers.json()["model_output_cost_usd_per_million_tokens"] is None
    assert tickets.status_code == 200
    assert len(tickets.json()) == 2


def test_provider_settings_expose_remote_status_without_secret(settings) -> None:
    remote_settings = replace(
        settings,
        allow_llm_inference=True,
        allow_cloud_fallback=True,
        remote_model_provider="anthropic",
        remote_model_base_url="https://api.example/v1",
        remote_model_name="documented-model",
        remote_model_api_key="do-not-return",
    )
    client = TestClient(create_app(remote_settings))

    response = client.get("/settings/providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["remote_model_provider"] == "anthropic"
    assert payload["remote_model_configured"] is True
    assert payload["remote_model_enabled"] is True
    assert "remote_model_api_key" not in payload
    assert "do-not-return" not in response.text


def test_provider_settings_report_remote_fallback_disabled_in_offline_mode(settings) -> None:
    offline_settings = replace(
        settings,
        allow_llm_inference=True,
        allow_cloud_fallback=True,
        offline_mode=True,
        remote_model_provider="anthropic",
        remote_model_base_url="https://api.example/v1",
        remote_model_name="documented-model",
        remote_model_api_key="do-not-return",
    )
    client = TestClient(create_app(offline_settings))

    response = client.get("/settings/providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["offline_mode"] is True
    assert payload["remote_model_configured"] is True
    assert payload["remote_model_enabled"] is False
    assert "do-not-return" not in response.text


def test_provider_health_is_admin_triggered_and_audited(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        system_module,
        "probe_model_providers",
        lambda active_settings: {
            "local": {"provider": "deterministic", "model": "llama3.1", "status": "ready", "probe": "not_required"},
            "remote": {"provider": None, "model": None, "status": "not_configured", "probe": "not_run"},
        },
    )
    client = TestClient(create_app(settings))

    response = client.get("/settings/providers/health")

    assert response.status_code == 200
    assert response.json()["local"]["status"] == "ready"
    assert response.json()["remote"]["status"] == "not_configured"
    assert any(event["event_type"] == "model_provider.health" for event in client.get("/audit").json())


def test_provider_health_requires_admin_role(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        system_module,
        "probe_model_providers",
        lambda active_settings: {
            "local": {"provider": "deterministic", "model": "llama3.1", "status": "ready", "probe": "not_required"},
            "remote": {"provider": None, "model": None, "status": "not_configured", "probe": "not_run"},
        },
    )
    secured = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
    )
    client = TestClient(create_app(secured))

    assert client.get("/settings/providers/health", headers={"Authorization": "Bearer viewer-token"}).status_code == 403
    assert client.get("/settings/providers/health", headers={"Authorization": "Bearer tech-token"}).status_code == 403
    admin_health = client.get("/settings/providers/health", headers={"Authorization": "Bearer admin-token"})
    assert admin_health.status_code == 200
    assert admin_health.json()["local"]["status"] == "ready"


def test_provider_settings_expose_operator_supplied_model_rates_without_secrets(settings) -> None:
    priced_settings = replace(
        settings,
        model_input_cost_usd_per_million_tokens=1.25,
        model_output_cost_usd_per_million_tokens=4.5,
        remote_model_api_key="do-not-return",
    )
    client = TestClient(create_app(priced_settings))

    response = client.get("/settings/providers")

    assert response.status_code == 200
    assert response.json()["model_input_cost_usd_per_million_tokens"] == 1.25
    assert response.json()["model_output_cost_usd_per_million_tokens"] == 4.5
    assert "do-not-return" not in response.text
