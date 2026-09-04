from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import wait_local_agent.api.routers.tenancy as tenancy_module
import wait_local_agent.baseline as baseline_module
from tests.api_helpers import _auth, _provision_bound_principal
from tests.support import ensure_test_client
from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients
from wait_local_agent.models import ClientCandidate, utc_now
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import Store


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/clients/acme/baselines"),
        ("GET", "/clients/acme/baselines"),
        ("POST", "/clients/acme/baselines/1/accept"),
        ("GET", "/clients/acme/drift"),
    ],
)
def test_baseline_routes_reject_unauthenticated_requests(settings, method: str, path: str) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        allow_write_actions=True,
        allow_http_probing=True,
        admin_token="bootstrap-admin",
    )
    client = TestClient(create_app(secure_settings))

    response = client.request(method, path)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/clients/acme/baselines"),
        ("GET", "/clients/acme/baselines"),
        ("POST", "/clients/acme/baselines/1/accept"),
        ("GET", "/clients/acme/drift"),
    ],
)
def test_baseline_routes_reject_non_msp_admin_requests(settings, method: str, path: str) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        allow_write_actions=True,
        allow_http_probing=True,
        admin_token="bootstrap-admin",
    )
    store = Store(secure_settings.data_path)
    ensure_test_client(store, "acme")
    _provision_bound_principal(store, "acme-admin", "tenant-admin", "acme", "admin")
    client = TestClient(create_app(secure_settings))

    response = client.request(method, path, headers=_auth("tenant-admin"))

    assert response.status_code == 403


def test_baseline_demo_mode_refuses_both_write_routes(settings) -> None:
    client = TestClient(create_app(settings))

    create_response = client.post("/clients/acme/baselines")
    accept_response = client.post("/clients/acme/baselines/1/accept")

    assert create_response.status_code == 403
    assert accept_response.status_code == 403


def test_baseline_routes_gate_live_drift_when_probing_is_disabled(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        allow_write_actions=True,
        allow_http_probing=False,
        admin_token="bootstrap-admin",
    )
    client = TestClient(create_app(secure_settings))

    response = client.get("/clients/acme/drift", headers=_auth("bootstrap-admin"))

    assert response.status_code == 409


def test_baseline_routes_return_unknown_client_and_version_404s_and_emit_audits(
    settings, monkeypatch
) -> None:
    monkeypatch.setattr(
        baseline_module,
        "build_dashboard_summary",
        lambda *_args, **_kwargs: {"summary": {}, "source_statuses": {}},
    )
    secure_settings = replace(
        settings,
        demo_mode=False,
        allow_write_actions=True,
        allow_http_probing=True,
        admin_token="bootstrap-admin",
    )
    store = Store(secure_settings.data_path)
    ensure_test_client(store, "acme")
    client = TestClient(create_app(secure_settings))
    headers = _auth("bootstrap-admin")

    created = client.post("/clients/acme/baselines", headers=headers)
    created_second = client.post("/clients/acme/baselines", headers=headers)
    accepted = client.post("/clients/acme/baselines/1/accept", headers=headers)
    listed = client.get("/clients/acme/baselines", headers=headers)
    drift = client.get("/clients/acme/drift", headers=headers)

    assert created.status_code == 201
    assert created_second.status_code == 201
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()] == [2, 1]
    assert drift.status_code == 200
    assert isinstance(drift.json()["findings"], list)

    unknown_client_responses = (
        client.post("/clients/missing/baselines", headers=headers),
        client.get("/clients/missing/baselines", headers=headers),
        client.post("/clients/missing/baselines/1/accept", headers=headers),
        client.get("/clients/missing/drift", headers=headers),
    )
    assert all(response.status_code == 404 for response in unknown_client_responses)
    assert client.post("/clients/acme/baselines/999/accept", headers=headers).status_code == 404
    assert client.get("/clients/acme/drift?baseline_version=999", headers=headers).status_code == 404

    event_types = {event.event_type for event in store.list_audit_events(client_id="acme")}
    assert {"baseline.created", "baseline.accepted", "baseline.listed", "baseline.drift.viewed"} <= event_types


def test_commercial_activation_routes_sanitize_store_errors_and_missing_clients(settings, monkeypatch) -> None:
    configured = replace(settings, demo_mode=False, admin_token="bootstrap-admin")
    store = Store(configured.data_path)
    ensure_test_client(store, "acme")
    application = create_app(configured)
    store = application.state.store
    context = AuthContext(Role.ADMIN, "bootstrap-admin", is_msp_admin=True)
    activate_route = next(
        route
        for route in application.routes
        if getattr(route, "path", None) == "/clients/{client_id}/commercial-activation"
        and getattr(route, "methods", set()) == {"POST"}
    )
    assert isinstance(activate_route, APIRoute)
    activate = activate_route.endpoint
    deactivate_route = next(
        route
        for route in application.routes
        if getattr(route, "path", None) == "/clients/{client_id}/commercial-activation"
        and getattr(route, "methods", set()) == {"DELETE"}
    )
    assert isinstance(deactivate_route, APIRoute)
    deactivate = deactivate_route.endpoint

    def reject_activation(*_args, **_kwargs):
        raise ValueError("invalid activation state")

    monkeypatch.setattr(store, "activate_commercial_client", reject_activation)
    with pytest.raises(HTTPException) as bad:
        activate("acme", context)
    assert bad.value.status_code == 400
    assert bad.value.detail == "invalid activation state"

    monkeypatch.setattr(store, "activate_commercial_client", lambda *_args, **_kwargs: None)
    with pytest.raises(HTTPException) as missing:
        activate("acme", context)
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as unknown:
        deactivate("missing", context)
    assert unknown.value.status_code == 404


def _discovery_settings(settings):
    return replace(
        settings,
        demo_mode=False,
        client_id="acme",
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
    )


def _api_discovery_candidate(
    instance_id: str,
    external_id: str,
    name: str,
    state: str = "unmatched",
    matched_client_id: str | None = None,
) -> ClientCandidate:
    now = utc_now()
    return ClientCandidate(
        candidate_id=f"candidate-{external_id}",
        connector_instance_id=instance_id,
        provider="connectwise",
        external_id=external_id,
        display_name=name,
        domains_json="[]",
        provenance="connectwise:test",
        first_seen=now,
        last_seen=now,
        match_state=state,
        matched_client_id=matched_client_id,
        match_reason="test discovery candidate",
        confidence=0.9 if state == "proposed" else 0.0,
    )

def test_client_discovery_mode_routes_enforce_operator_and_persist(settings) -> None:
    demo_client = TestClient(create_app(settings))
    assert demo_client.get("/setup/mode").json() == {"mode": None}
    blocked = demo_client.put("/setup/mode", json={"mode": "msp"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "client discovery is unavailable in demo mode"

    secure_app = create_app(_discovery_settings(settings))
    store = secure_app.state.store
    ensure_test_client(store, "acme")
    store.create_principal("client-admin", kind="staff")
    store.add_principal_credential("client-admin", "client-admin-token")
    store.add_principal_client_role("client-admin", "acme", "admin")
    client = TestClient(secure_app)

    not_msp = client.put("/setup/mode", headers=_auth("client-admin-token"), json={"mode": "msp"})
    assert not_msp.status_code == 403
    assert not_msp.json()["detail"] == "msp operator access required"
    updated = client.put("/setup/mode", headers=_auth("admin-token"), json={"mode": "msp"})
    assert updated.status_code == 200
    assert updated.json() == {"mode": "msp"}
    assert client.get("/setup/mode", headers=_auth("viewer-token")).json() == {"mode": "msp"}
    assert client.put("/setup/mode", headers=_auth("admin-token"), json={"mode": "smb"}).json() == {
        "mode": "smb"
    }


def test_client_discovery_run_and_list_routes_cover_selection_and_failures(settings, monkeypatch) -> None:
    app = create_app(_discovery_settings(settings))
    client = TestClient(app)
    store = app.state.store
    active = store.create_connector_instance("connectwise", "Active PSA")
    assert store.update_connector_instance(active.connector_instance_id, status="active") is not None
    inactive = store.create_connector_instance("connectwise", "Inactive PSA")
    unsupported = store.create_connector_instance("m365", "Not a PSA")

    missing = client.post(
        "/discovery/clients/run",
        headers=_auth("admin-token"),
        json={"connector_instance_id": "missing-instance"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "connector instance not found"
    non_psa = client.post(
        "/discovery/clients/run",
        headers=_auth("admin-token"),
        json={"connector_instance_id": unsupported.connector_instance_id},
    )
    assert non_psa.status_code == 409
    assert non_psa.json()["detail"] == "connector instance is not a supported PSA instance"

    inactive_run = client.post(
        "/discovery/clients/run",
        headers=_auth("admin-token"),
        json={"connector_instance_id": inactive.connector_instance_id},
    )
    assert inactive_run.status_code == 200
    assert inactive_run.json()["candidates"] == []
    assert inactive_run.json()["failures"][0]["detail"] == "connector instance is not active"

    candidate = _api_discovery_candidate(active.connector_instance_id, "42", "Acme Ltd", "proposed", "acme")
    calls: list[str] = []

    def fake_discover(_store, instance, *, settings, vault):
        calls.append(instance.connector_instance_id)
        if instance.connector_instance_id == inactive.connector_instance_id:
            raise tenancy_module.ClientDiscoveryError("provider unavailable")
        return [candidate]

    monkeypatch.setattr(tenancy_module, "discover_instance", fake_discover)
    selected = client.post(
        "/discovery/clients/run",
        headers=_auth("admin-token"),
        json={"connector_instance_id": active.connector_instance_id},
    )
    assert selected.status_code == 200
    assert selected.json()["candidates"][0]["candidate_id"] == candidate.candidate_id
    assert calls == [active.connector_instance_id]

    all_instances = client.post("/discovery/clients/run", headers=_auth("admin-token"), json={})
    assert all_instances.status_code == 200
    assert all_instances.json()["failures"] == [
        {"connector_instance_id": inactive.connector_instance_id, "detail": "provider unavailable"}
    ]
    assert set(calls) == {active.connector_instance_id, inactive.connector_instance_id}

    for state in ("verified", "proposed", "ambiguous", "unmatched", "conflicting", "dismissed"):
        store.upsert_client_candidate(
            _api_discovery_candidate(active.connector_instance_id, f"{state}-id", state.title(), state)
        )
    listing = client.get(
        "/discovery/clients",
        headers=_auth("admin-token"),
        params={"match_state": "proposed", "page": 2, "page_size": 1},
    )
    assert listing.status_code == 200
    assert listing.json()["page"] == 2
    assert listing.json()["page_size"] == 1
    assert listing.json()["items"] == []
    assert listing.json()["summary"] == {
        "discovered": 5,
        "reconciled": 1,
        "need_confirmation": 2,
        "unmatched": 1,
        "conflicts": 1,
    }


def test_client_discovery_accept_routes_cover_guards_conflicts_and_success(settings, monkeypatch) -> None:
    app = create_app(_discovery_settings(settings))
    client = TestClient(app)
    store = app.state.store
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("acme", "Acme")
    store.create_client("other", "Other")
    store.create_client("missing-client", "Missing Client")

    ambiguous = _api_discovery_candidate(instance.connector_instance_id, "ambiguous", "Ambiguous", "ambiguous")
    conflicting = _api_discovery_candidate(instance.connector_instance_id, "conflicting", "Conflicting", "conflicting")
    stale = _api_discovery_candidate(instance.connector_instance_id, "stale", "Stale", "proposed", "missing-client")
    for candidate in (ambiguous, conflicting, stale):
        store.upsert_client_candidate(candidate)
    assert client.post(
        f"/discovery/clients/{ambiguous.candidate_id}/accept", headers=_auth("admin-token")
    ).status_code == 409
    assert client.post(
        f"/discovery/clients/{conflicting.candidate_id}/accept", headers=_auth("admin-token")
    ).status_code == 409
    original_get_client = store.get_client
    monkeypatch.setattr(
        store,
        "get_client",
        lambda scope, client_id: (
            None
            if client_id == "missing-client"
            else original_get_client(scope, client_id)
        ),
    )
    assert client.post(
        f"/discovery/clients/{stale.candidate_id}/accept", headers=_auth("admin-token")
    ).json()["detail"] == "the proposed client no longer exists"
    monkeypatch.undo()
    assert client.post(
        "/discovery/clients/does-not-exist/accept", headers=_auth("admin-token")
    ).status_code == 404

    existing_mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "already-mapped", "other"
    )
    store.verify_client_connector_mapping(AllClients(), existing_mapping.mapping_id)
    conflicting_mapping = _api_discovery_candidate(
        instance.connector_instance_id, "already-mapped", "Acme", "proposed", "acme"
    )
    store.upsert_client_candidate(conflicting_mapping)
    response = client.post(
        f"/discovery/clients/{conflicting_mapping.candidate_id}/accept", headers=_auth("admin-token")
    )
    assert response.status_code == 409
    assert "different verified mapping" in response.json()["detail"]

    generic = _api_discovery_candidate(instance.connector_instance_id, "generic", "Acme", "proposed", "acme")
    store.upsert_client_candidate(generic)

    def raise_mapping_error(*_args, **_kwargs):
        raise ValueError("simulated mapping failure")

    monkeypatch.setattr(store, "create_client_connector_mapping", raise_mapping_error)
    generic_response = client.post(
        f"/discovery/clients/{generic.candidate_id}/accept", headers=_auth("admin-token")
    )
    assert generic_response.status_code == 409
    assert generic_response.json()["detail"] == "candidate mapping could not be created"
    monkeypatch.undo()

    accepted = _api_discovery_candidate(instance.connector_instance_id, "accepted", "Acme", "proposed", "acme")
    store.upsert_client_candidate(accepted)
    success = client.post(
        f"/discovery/clients/{accepted.candidate_id}/accept", headers=_auth("admin-token")
    )
    assert success.status_code == 200
    assert success.json()["match_state"] == "verified"
    assert success.json()["mapping"]["verified"] == 1


def test_client_discovery_bulk_accept_routes_guard_missing_and_non_proposed_candidates(settings) -> None:
    app = create_app(_discovery_settings(settings))
    client = TestClient(app)
    store = app.state.store
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("acme", "Acme")
    store.create_client("beta", "Beta")
    proposed = [
        _api_discovery_candidate(instance.connector_instance_id, "bulk-acme", "Acme", "proposed", "acme"),
        _api_discovery_candidate(instance.connector_instance_id, "bulk-beta", "Beta", "proposed", "beta"),
    ]
    ambiguous = _api_discovery_candidate(instance.connector_instance_id, "bulk-ambiguous", "Ambiguous", "ambiguous")
    for candidate in [*proposed, ambiguous]:
        store.upsert_client_candidate(candidate)

    missing = client.post(
        "/discovery/clients/accept-proposed",
        headers=_auth("admin-token"),
        json={"candidate_ids": ["missing-candidate"]},
    )
    assert missing.status_code == 404
    refused = client.post(
        "/discovery/clients/accept-proposed",
        headers=_auth("admin-token"),
        json={"candidate_ids": [ambiguous.candidate_id]},
    )
    assert refused.status_code == 409
    assert "proposed" in refused.json()["detail"]

    accepted = client.post(
        "/discovery/clients/accept-proposed",
        headers=_auth("admin-token"),
        json={"candidate_ids": [candidate.candidate_id for candidate in proposed]},
    )
    assert accepted.status_code == 200
    assert len(accepted.json()["accepted"]) == 2
    assert all(item["match_state"] == "verified" for item in accepted.json()["accepted"])


def test_client_discovery_create_and_dismiss_routes_cover_state_guards_and_success(settings) -> None:
    app = create_app(_discovery_settings(settings))
    client = TestClient(app)
    store = app.state.store
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("acme", "Acme")
    verified = _api_discovery_candidate(instance.connector_instance_id, "verified", "Verified", "verified", "acme")
    dismissed = _api_discovery_candidate(instance.connector_instance_id, "dismissed", "Dismissed", "dismissed")
    proposed = _api_discovery_candidate(instance.connector_instance_id, "dismiss", "Dismiss me", "proposed", "acme")
    unmatched = _api_discovery_candidate(instance.connector_instance_id, "new-client", "New Client")
    for candidate in (verified, dismissed, proposed, unmatched):
        store.upsert_client_candidate(candidate)

    assert client.post(
        "/discovery/clients/missing/create-client", headers=_auth("admin-token")
    ).status_code == 404
    assert client.post(
        f"/discovery/clients/{verified.candidate_id}/create-client", headers=_auth("admin-token")
    ).json()["detail"] == "candidate cannot create a client in its current state"
    assert client.post(
        f"/discovery/clients/{dismissed.candidate_id}/create-client", headers=_auth("admin-token")
    ).status_code == 409
    assert client.post(
        f"/discovery/clients/{verified.candidate_id}/dismiss", headers=_auth("admin-token")
    ).status_code == 409
    assert client.post(
        "/discovery/clients/missing/dismiss", headers=_auth("admin-token")
    ).status_code == 404

    store.create_client("other", "Other")
    existing_mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "already-linked", "other"
    )
    store.verify_client_connector_mapping(AllClients(), existing_mapping.mapping_id)
    mapping_conflict = _api_discovery_candidate(instance.connector_instance_id, "already-linked", "New Client")
    store.upsert_client_candidate(mapping_conflict)
    conflict_response = client.post(
        f"/discovery/clients/{mapping_conflict.candidate_id}/create-client", headers=_auth("admin-token")
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["detail"] == "client or candidate mapping already exists"

    created = client.post(
        f"/discovery/clients/{unmatched.candidate_id}/create-client", headers=_auth("admin-token")
    )
    assert created.status_code == 200
    assert created.json()["match_state"] == "verified"
    assert created.json()["client"]["client_id"].startswith("discovered-")

    dismissed_response = client.post(
        f"/discovery/clients/{proposed.candidate_id}/dismiss", headers=_auth("admin-token")
    )
    assert dismissed_response.status_code == 200
    assert dismissed_response.json()["match_state"] == "dismissed"
