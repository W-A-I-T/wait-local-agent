from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients, BoundClients
from wait_local_agent.store import Store


def test_commercial_activation_store_is_idempotent_and_tenant_scoped(settings) -> None:
    store = Store(settings.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    alpha_scope = BoundClients(frozenset({"alpha"}))

    first = store.activate_commercial_client(alpha_scope, "alpha", "operator", now="2026-09-01T00:00:00Z")
    second = store.activate_commercial_client(alpha_scope, "alpha", "other", now="2026-09-02T00:00:00Z")

    assert first == second
    assert [item.client_id for item in store.list_commercial_activations(AllClients())] == ["alpha"]
    assert store.list_commercial_activations(BoundClients(frozenset({"beta"}))) == []
    assert store.deactivate_commercial_client(BoundClients(frozenset({"beta"})), "alpha") is False
    assert store.deactivate_commercial_client(alpha_scope, "alpha") is True
    assert store.list_commercial_activations(AllClients()) == []


def test_entitlement_and_activation_routes_are_neutral_and_audited(settings) -> None:
    live_settings = replace(settings, demo_mode=False, admin_token="admin-token")
    app = create_app(live_settings)
    store = app.state.store
    store.create_client("alpha", "Alpha")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-token"}

    assert client.get("/entitlement", headers=headers).json() == {"commercial": None}
    before = client.get("/clients", headers=headers).json()
    activated = client.post("/clients/alpha/commercial-activation", headers=headers)
    assert activated.status_code == 200
    assert client.get("/clients", headers=headers).json() == before
    assert client.get("/clients/commercial-activations", headers=headers).json()[0]["client_id"] == "alpha"
    assert any(event.event_type == "commercial.client_activated" for event in store.list_audit_events())

    deactivated = client.delete("/clients/alpha/commercial-activation", headers=headers)
    assert deactivated.status_code == 200
    assert deactivated.json() == {"client_id": "alpha", "commercial_managed": False}
    assert client.get("/clients", headers=headers).json() == before
    assert any(event.event_type == "commercial.client_deactivated" for event in store.list_audit_events())


def test_demo_mode_refuses_commercial_activation(settings) -> None:
    app = create_app(settings)
    store = app.state.store
    store.create_client("demo-client", "Demo Client")
    response = TestClient(app).post("/clients/demo-client/commercial-activation")

    assert response.status_code == 403
    assert store.list_commercial_activations(AllClients()) == []
