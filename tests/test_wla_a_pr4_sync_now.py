from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.ingestion_poller import PollSummary


def _active_instance(app, display_name: str) -> str:
    instance = app.state.store.create_connector_instance("halopsa", display_name)
    instance = app.state.store.update_connector_instance(instance.connector_instance_id, status="active")
    assert instance is not None
    return instance.connector_instance_id


def test_sync_now_operator_runs_and_returns_poll_summary_without_credentials(settings, monkeypatch) -> None:
    active_settings = replace(
        settings,
        demo_mode=False,
        admin_token="bootstrap-admin",
        allow_http_probing=True,
    )

    class FakePoller:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def poll_instance(self, connector_instance_id: str, **_kwargs) -> PollSummary:
            return PollSummary(connector_instance_id, 1, 2, 0, "idle", "completed")

    monkeypatch.setattr(app_module, "IngestionPoller", FakePoller)
    app = create_app(active_settings)
    app.state.store.create_principal("msp-admin", kind="staff")
    app.state.store.add_principal_credential("msp-admin", "msp-secret")
    app.state.store.add_principal_global_role("msp-admin")
    connector_instance_id = _active_instance(app, "Primary")

    client = TestClient(app)
    response = client.post(
        f"/connectors/instances/{connector_instance_id}/sync",
        headers={"Authorization": "Bearer msp-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "idle"
    assert "credential" not in payload
    assert "credential_ref" not in payload
    assert any(
        event["event_type"] == "connector.sync_triggered"
        for event in client.get("/audit", headers={"Authorization": "Bearer msp-secret"}).json()
    )


def test_sync_now_rejects_non_operator(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        viewer_token="viewer-token",
        allow_http_probing=True,
    )
    app = create_app(secure_settings)
    connector_instance_id = _active_instance(app, "Non-operator")

    client = TestClient(app)
    response = client.post(
        f"/connectors/instances/{connector_instance_id}/sync",
        headers={"Authorization": "Bearer viewer-token"},
    )

    assert response.status_code == 403


def test_sync_now_rejects_missing_disabled_and_inactive_instances(settings, monkeypatch) -> None:
    class FakePoller:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def poll_instance(self, *_args, **_kwargs) -> PollSummary:
            raise AssertionError("poll_instance must not be called")

    monkeypatch.setattr(app_module, "IngestionPoller", FakePoller)
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/connectors/instances/missing/sync").status_code == 404

    probing_off_instance = _active_instance(app, "Probing-off")
    probing_off = client.post(f"/connectors/instances/{probing_off_instance}/sync")
    assert probing_off.status_code == 409

    active_settings = replace(settings, allow_http_probing=True)
    inactive_app = create_app(active_settings)
    inactive_id = _active_instance(inactive_app, "Inactive")
    inactive_app.state.store.update_connector_instance(inactive_id, status="disabled")
    inactive = TestClient(inactive_app).post(f"/connectors/instances/{inactive_id}/sync")
    assert inactive.status_code == 409
