from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Literal, cast

import pytest
from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
import wait_local_agent.api.routers.psa_connectors as psa_connectors_module
import wait_local_agent.api.routers.scheduled_jobs as scheduled_jobs_module
import wait_local_agent.baseline as baseline_module
from tests.api_helpers import _auth, _provision_bound_principal, _read_response
from tests.support import ensure_test_client, ensure_test_clients, ingest_local
from wait_local_agent.api.app import ClientReportRequest, create_app
from wait_local_agent.collectors import (
    default_registry,
)
from wait_local_agent.connectwise import ConnectWiseReadResponse
from wait_local_agent.models import (
    ClientCandidate,
    ConnectorReadResult,
    ConnectWiseWriteRequest,
    ConnectWiseWriteResult,
    HaloReadResult,
    HaloTicket,
    HaloWriteRequest,
    HaloWriteResult,
    utc_now,
)
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import Store


def test_app_rejects_invalid_secrets_backend_at_construction(settings) -> None:
    invalid_settings = replace(settings, secrets_backend="vault")

    with pytest.raises(ValueError, match=r"WAIT_SECRETS_BACKEND=.*vault"):
        create_app(invalid_settings)


def test_validation_errors_redact_sensitive_route_inputs(settings) -> None:
    client = TestClient(create_app(settings))

    local_login = client.post("/auth/login/local", json={})
    pack_install = client.post("/packs/install", json={})

    assert local_login.status_code == 422
    assert pack_install.status_code == 422
    assert local_login.json()["detail"][0]["loc"][-1] == "token"
    assert pack_install.json()["detail"][0]["loc"][-1] == "tarball_path"


def test_api_lists_exactly_fourteen_collector_modules(settings, isolated_default_registry) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/collectors/modules")

    assert response.status_code == 200
    modules = response.json()
    registered_ids = [module.manifest.id for module in default_registry.list()]
    assert [module["id"] for module in modules] == registered_ids
    assert len(modules) == len(registered_ids) == 14


def test_api_auth_is_off_in_default_demo_mode(settings) -> None:
    demo_settings = settings.__class__(
        **{**settings.__dict__, "api_token": "local-secret", "demo_mode": True}
    )
    client = TestClient(create_app(demo_settings))

    response = client.get("/health")
    security = client.get("/settings/security")

    assert response.status_code == 200
    assert response.json()["api_auth_required"] is False
    assert security.status_code == 200
    assert security.json()["api_token_configured"] is True
    assert security.json()["api_auth_required"] is False


def test_api_auth_requires_bearer_token_when_demo_mode_disabled(settings) -> None:
    secure_settings = settings.__class__(
        **{**settings.__dict__, "api_token": "local-secret", "demo_mode": False}
    )
    client = TestClient(create_app(secure_settings))

    missing = client.get("/health")
    malformed = client.get("/health", headers={"Authorization": "Token local-secret"})
    wrong = client.get("/health", headers={"Authorization": "Bearer wrong"})
    good = client.get("/health", headers={"Authorization": "Bearer local-secret"})
    security = client.get("/settings/security", headers={"Authorization": "Bearer local-secret"})

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert wrong.status_code == 401
    assert good.status_code == 200
    assert good.json()["api_auth_required"] is True
    assert security.status_code == 200
    assert security.json()["api_auth_required"] is True


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


def test_audit_event_export_json_and_csv(settings) -> None:
    store = Store(settings.data_path)
    store.add_audit_event("unit.test.earlier", "TCK-1", "first")
    store.add_audit_event("unit.test.later", "TCK-2", "second")
    client = TestClient(create_app(settings))

    json_export = client.get("/audit-events/export")
    csv_export = client.get("/audit-events/export", params={"format": "csv"})
    future_filter = client.get("/audit-events/export", params={"from": "9999-01-01T00:00:00+00:00"})

    assert json_export.status_code == 200
    assert json_export.json()["count"] >= 2
    assert any(event["event_type"] == "unit.test.earlier" for event in json_export.json()["events"])
    assert any(event["event_type"] == "unit.test.later" for event in json_export.json()["events"])
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert "id,event_type,subject_id,detail,created_at" in csv_export.text
    assert "unit.test.earlier" in csv_export.text
    assert "unit.test.later" in csv_export.text
    assert future_filter.status_code == 200
    assert future_filter.json() == {"count": 0, "events": []}

def test_auth_role_approver_identity_and_client_filters(settings) -> None:
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
    ensure_test_clients(store, "acme", "beta")
    _provision_bound_principal(store, "acme-viewer", "acme-viewer-token", "acme", "viewer")
    _provision_bound_principal(store, "acme-technician", "acme-technician-token", "acme", "technician")
    with store._connect() as connection:
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-ACME', 'Acme', 'Subject', 'Body', 'High', 'Open', 'acme')
            """
        )
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-BETA', 'Beta', 'Subject', 'Body', 'Low', 'Open', 'beta')
            """
        )
    approval = store.create_approval_request(
        "TCK-ACME",
        "ticket.assign",
        {"ticket_id": "TCK-ACME"},
        client_id="acme",
    )
    store.create_approval_request("TCK-BETA", "ticket.assign", {"ticket_id": "TCK-BETA"}, client_id="beta")
    store.add_audit_event("unit.test", "TCK-ACME", "acme event", client_id="acme")
    store.add_audit_event("unit.test", "TCK-BETA", "beta event", client_id="beta")
    store.create_workflow_run(
        "documentation-assisted-response",
        "TCK-ACME",
        "pending_approval",
        "acme",
        approval.id,
        client_id="acme",
    )
    store.upsert_knowledge_document(
        path="examples/sample_docs/acme.md",
        title="Acme",
        kind="markdown",
        checksum="sum-acme",
        modified_at="2026-07-08T00:00:00+00:00",
        chunks=["chunk"],
        client_id="acme",
    )
    client = TestClient(create_app(secure_settings))

    role = client.get("/auth/role", headers={"Authorization": "Bearer viewer-token"})
    filtered_tickets = client.get("/tickets", params={"client_id": "acme"}, headers=_auth("acme-viewer-token"))
    filtered_approvals = client.get(
        "/approval-requests", params={"client_id": "acme"}, headers=_auth("acme-viewer-token")
    )
    narrowed_approvals = client.get(
        "/approval-requests", params={"client_id": "beta"}, headers=_auth("acme-viewer-token")
    )
    filtered_audit = client.get("/audit", params={"client_id": "acme"}, headers=_auth("acme-viewer-token"))
    filtered_documents = client.get(
        "/knowledge/documents", params={"client_id": "acme"}, headers=_auth("acme-viewer-token")
    )
    filtered_runs = client.get("/workflow-runs", params={"client_id": "acme"}, headers=_auth("acme-viewer-token"))
    ticket_approval = client.post(
        "/tickets/TCK-ACME/approvals",
        headers=_auth("acme-technician-token"),
        json={"status": "approved", "comment": "ship it"},
    )
    approved = client.post(
        f"/approval-requests/{approval.id}",
        headers=_auth("acme-technician-token"),
        json={"status": "approved", "comment": "ship it"},
    )
    export = client.get("/audit-events/export", params={"client_id": "acme"}, headers=_auth("admin-token"))
    expected_approver_id = hashlib.sha256(b"acme-technician-token").hexdigest()[:16]

    assert role.status_code == 200
    assert role.json()["role"] == "viewer"
    assert [ticket["id"] for ticket in filtered_tickets.json()] == ["TCK-ACME"]
    assert [request["subject_id"] for request in filtered_approvals.json()] == ["TCK-ACME"]
    assert narrowed_approvals.status_code == 403
    assert all(event["client_id"] == "acme" for event in filtered_audit.json())
    assert [document["title"] for document in filtered_documents.json()] == ["Acme"]
    assert [run["ticket_id"] for run in filtered_runs.json()] == ["TCK-ACME"]
    assert ticket_approval.status_code == 200
    assert ticket_approval.json() == {
        "ticket_id": "TCK-ACME",
        "status": "approved",
        "comment": "ship it",
    }
    assert approved.status_code == 200
    assert approved.json()["approver_id"] == expected_approver_id
    assert any(
        event["event_type"] == "approval.updated" and event["client_id"] == "acme"
        for event in client.get("/audit", params={"client_id": "acme"}, headers=_auth("acme-viewer-token")).json()
    )
    assert any(
        event["event_type"] == "approval_request.updated" and event["approver_id"] == expected_approver_id
        for event in export.json()["events"]
    )


def test_knowledge_authority_route_is_admin_scoped_and_records_authenticated_actor(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="bootstrap-admin-token",
        tech_token="technician-token",
        viewer_token="viewer-token",
    )
    store = Store(secure_settings.data_path)
    ensure_test_clients(store, "acme", "beta")
    _provision_bound_principal(store, "acme-admin", "acme-admin-token", "acme", "admin")
    first = store.upsert_knowledge_document(
        path="examples/sample_docs/authority-first.md",
        title="First SOP",
        kind="markdown",
        checksum="authority-first-sum",
        modified_at="2026-08-31T00:00:00+00:00",
        chunks=["first"],
        client_id="acme",
    )
    replacement = store.upsert_knowledge_document(
        path="examples/sample_docs/authority-replacement.md",
        title="Replacement SOP",
        kind="markdown",
        checksum="authority-replacement-sum",
        modified_at="2026-08-31T00:00:00+00:00",
        chunks=["replacement"],
        client_id="acme",
    )
    foreign = store.upsert_knowledge_document(
        path="examples/sample_docs/authority-foreign.md",
        title="Foreign SOP",
        kind="markdown",
        checksum="authority-foreign-sum",
        modified_at="2026-08-31T00:00:00+00:00",
        chunks=["foreign"],
        client_id="beta",
    )
    client = TestClient(create_app(secure_settings))

    denied = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("technician-token"),
        json={"authority": "REFERENCE"},
    )
    rejected_body = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "APPROVED_SOP", "approved_by": "request-body-actor"},
    )
    promoted = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "APPROVED_SOP", "sop_version": "2026.08", "superseded_by": replacement.id},
    )
    invalid_superseded_scope = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "APPROVED_SOP", "superseded_by": foreign.id},
    )
    foreign_mutation = client.patch(
        f"/knowledge/documents/{foreign.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "REFERENCE"},
    )
    demoted = client.patch(
        f"/knowledge/documents/{first.id}/authority",
        headers=_auth("acme-admin-token"),
        json={"authority": "REFERENCE"},
    )
    listed = client.get("/knowledge/documents", headers=_auth("acme-admin-token"))
    audit = client.get("/audit", params={"client_id": "acme"}, headers=_auth("acme-admin-token"))

    assert denied.status_code == 403
    assert rejected_body.status_code == 422
    assert promoted.status_code == 200
    assert promoted.json()["authority"] == "APPROVED_SOP"
    assert promoted.json()["approved_by"] == hashlib.sha256(b"acme-admin-token").hexdigest()[:16]
    assert promoted.json()["approved_at"]
    assert promoted.json()["sop_version"] == "2026.08"
    assert promoted.json()["superseded_by"] == replacement.id
    assert invalid_superseded_scope.status_code == 400
    assert foreign_mutation.status_code == 404
    assert demoted.status_code == 200
    assert demoted.json()["authority"] == "REFERENCE"
    assert demoted.json()["approved_by"] is None
    assert demoted.json()["approved_at"] is None
    listed_documents = listed.json()
    assert [document["authority"] for document in listed_documents] == ["REFERENCE", "UNTRUSTED"]
    # The beta document must not appear in an acme-scoped listing.
    assert foreign.id not in {document["id"] for document in listed_documents}
    assert {"authority", "sop_version", "approved_by", "approved_at", "superseded_by"} <= set(listed_documents[0])
    authority_events = [event for event in audit.json() if event["event_type"] == "knowledge.authority.changed"]
    assert len(authority_events) == 2
    expected_actor = hashlib.sha256(b"acme-admin-token").hexdigest()[:16]
    # Audit events are returned newest-first by Store.list_audit_events (order by id desc).
    assert authority_events[0]["detail"] == (
        f"actor={expected_actor} document_id={first.id} "
        "old_authority=APPROVED_SOP new_authority=REFERENCE"
    )
    assert authority_events[0]["approver_id"] == expected_actor
    assert authority_events[1]["detail"] == (
        f"actor={expected_actor} document_id={first.id} "
        "old_authority=UNTRUSTED new_authority=APPROVED_SOP"
    )
    assert authority_events[1]["approver_id"] == expected_actor


def test_knowledge_api_ingest_list_and_search(settings) -> None:
    client = TestClient(create_app(settings))

    ingest = client.post("/knowledge/ingest", json={"path": "examples/sample_docs"})
    documents = client.get("/knowledge/documents")
    search = client.get("/knowledge/search", params={"q": "mailbox permissions"})

    assert ingest.status_code == 200
    assert len(ingest.json()) == 3
    assert documents.status_code == 200
    assert len(documents.json()) == 3
    assert search.status_code == 200
    assert search.json()[0]["title"] == "Shared Mailbox Runbook"


def test_knowledge_search_scopes_results_by_client_id(settings) -> None:
    store = Store(settings.data_path)
    ensure_test_clients(store, "acme", "beta")
    store.upsert_knowledge_document(
        path="examples/sample_docs/acme.md",
        title="Acme Runbook",
        kind="markdown",
        checksum="acme-checksum",
        modified_at="2026-07-08T00:00:00+00:00",
        chunks=["mailbox permissions for acme"],
        client_id="acme",
    )
    store.upsert_knowledge_document(
        path="examples/sample_docs/beta.md",
        title="Beta Runbook",
        kind="markdown",
        checksum="beta-checksum",
        modified_at="2026-07-08T00:00:00+00:00",
        chunks=["mailbox permissions for beta"],
        client_id="beta",
    )
    client = TestClient(create_app(settings))

    filtered = client.get("/knowledge/search", params={"q": "mailbox permissions", "client_id": "acme"})
    unfiltered = client.get("/knowledge/search", params={"q": "mailbox permissions"})

    assert filtered.status_code == 200
    assert [chunk["title"] for chunk in filtered.json()] == ["Acme Runbook"]
    assert len(unfiltered.json()) == 2


def test_knowledge_api_rejects_outside_allowed_root(settings, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": str(outside)})

    assert response.status_code == 400


def test_connector_workflow_approval_and_event_surfaces(settings) -> None:
    ingest_local(Store(settings.data_path), Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    connectors = client.get("/connectors")
    secrets = client.get("/secrets")
    templates = client.get("/workflows/templates")
    run = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        json={"ticket_id": "TCK-1002"},
    )
    draft = client.post(
        "/connectors/halopsa/tickets/TCK-1002/drafts",
        json={"action_type": "add_note", "fields": {"note": "Draft ready"}},
    )
    approvals = client.get("/approval-requests")
    update = client.post(
        f"/approval-requests/{draft.json()['approval_request_id']}",
        json={"status": "approved", "comment": "approve with edits"},
    )
    events = client.get("/event-history")
    workflow_runs = client.get("/workflow-runs")

    assert connectors.status_code == 200
    assert connectors.json()[0]["id"] == "halopsa"
    assert any(connector["id"] == "hudu" for connector in connectors.json())
    assert secrets.status_code == 403
    assert templates.status_code == 200
    assert len(templates.json()) == 24
    assert any(item["tool_id"] == "ticket-quality" for item in templates.json())
    assert any(item["tool_id"] == "dispatch-suggestion" for item in templates.json())
    assert {
        item["id"] for item in templates.json() if item["id"].startswith("m365-")
    } == {
        "m365-user-onboarding-review",
        "m365-user-offboarding-review",
        "m365-password-reset-review",
            "m365-authentication-method-removal-review",
        "m365-license-request-review",
        "m365-compliance-review",
        "m365-inactive-license-review",
    }
    assert all(
        item["approval_required"]
        for item in templates.json()
        if item["id"].startswith("m365-")
        and item["id"] not in {"m365-compliance-review", "m365-inactive-license-review"}
    )
    assert next(
        item["approval_required"]
        for item in templates.json()
        if item["id"] == "m365-compliance-review"
    ) is False
    assert next(
        item["approval_required"]
        for item in templates.json()
        if item["id"] == "m365-inactive-license-review"
    ) is False
    sla_template = next(item for item in templates.json() if item["id"] == "ticket-sla-risk-review")
    assert sla_template["payload_schema"]["required"] == ["thresholds_minutes"]
    assert run.status_code == 200
    assert run.json()["status"] == "pending_approval"
    assert draft.status_code == 200
    assert draft.json()["approval_required"] is True
    assert approvals.status_code == 200
    assert len(approvals.json()) == 2
    assert update.status_code == 200
    assert update.json()["comment"] == "approve with edits"
    assert events.status_code == 200
    assert any(event["event_type"] == "workflow.execution" for event in events.json())
    assert workflow_runs.status_code == 200
    assert workflow_runs.json()[0]["template_id"] == "documentation-assisted-response"
    assert workflow_runs.json()[0]["status"] == "pending_approval"


def test_recurring_service_review_report_route_is_bounded_and_client_scoped(settings) -> None:
    store = Store(settings.data_path)
    ensure_test_client(store, "acme")
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    endpoint = next(
        route.endpoint
        for route in create_app(settings).routes
        if isinstance(route, APIRoute)
        and route.path == "/reports/recurring-service-review"
        and route.methods is not None
        and "POST" in route.methods
    )
    context = AuthContext(role=Role.ADMIN, presented_token="demo", demo_mode=True)
    response = endpoint(
        ClientReportRequest(
            client_id="acme",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
        ),
        context,
        follow_up_after_days=14,
    )
    with pytest.raises(HTTPException, match="between 1 and 90"):
        endpoint(
            ClientReportRequest(
                client_id="acme",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 3, 31),
            ),
            context,
            follow_up_after_days=0,
        )
    with pytest.raises(HTTPException, match="client_id is required"):
        endpoint(
            ClientReportRequest(
                period_start=date(2026, 1, 1),
                period_end=date(2026, 3, 31),
            ),
            context,
            follow_up_after_days=14,
        )
    with pytest.raises(HTTPException, match="on or after"):
        endpoint(
            ClientReportRequest(
                client_id="acme",
                period_start=date(2026, 3, 31),
                period_end=date(2026, 1, 1),
            ),
            context,
            follow_up_after_days=14,
        )

    assert response["report_type"] == "recurring_service_review"
    assert response["client_id"] == "acme"
    assert response["metadata"]["scope"] == "single client"




def test_invalid_halopsa_draft_returns_400(settings, monkeypatch) -> None:
    client = TestClient(create_app(settings))

    def fail_draft(*args, **kwargs):
        raise ValueError("bad draft")

    monkeypatch.setattr(psa_connectors_module, "draft_halopsa_ticket_action", fail_draft)

    response = client.post(
        "/connectors/halopsa/tickets/TCK-1002/drafts",
        json={"action_type": "add_note", "fields": {"note": "ok"}},
    )

    assert response.status_code == 400


def test_new_api_error_edges_and_redaction(settings, monkeypatch) -> None:
    class ReadyHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return HaloReadResult("ready", "write ok", 0)

    store = Store(settings.data_path)
    approval = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "HALO-1",
            "action_type": "add_note",
            "fields": {"note": "Ready"},
            "api_key": "secret",
            "authorization": "Bearer secret",
            "nested": {"access_token": "secret"},
            "list": [{"client_secret": "secret"}],
        },
    )
    store.update_approval_request(approval.id or 0, "approved")
    monkeypatch.setattr(app_module, "HaloPSAClient", ReadyHaloClient)
    client = TestClient(app_module.create_app(settings))

    missing_approval = client.get("/approval-requests/999")
    missing_edit = client.patch("/approval-requests/999/payload", json={"fields": {"note": "x"}})
    bad_edit = client.patch(f"/approval-requests/{approval.id}/payload", json={"fields": {}})
    ready = client.get(f"/approval-requests/{approval.id}")
    missing_workflow = client.get("/workflow-runs/999")
    bad_search = client.get("/knowledge/search", params={"q": "x", "backend": "nope"})
    missing_ticket_workflow = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        json={"ticket_id": "NOPE"},
    )

    assert missing_approval.status_code == 404
    assert missing_edit.status_code == 404
    assert bad_edit.status_code == 400
    assert ready.json()["can_execute"] is True
    assert ready.json()["payload"]["api_key"] == "[redacted]"
    assert ready.json()["payload"]["authorization"] == "[redacted]"
    assert ready.json()["payload"]["nested"]["access_token"] == "[redacted]"
    assert ready.json()["payload"]["list"][0]["client_secret"] == "[redacted]"
    assert missing_workflow.status_code == 404
    assert bad_search.status_code == 400
    assert missing_ticket_workflow.status_code == 404
    assert app_module._safe_json_object("not-json") == {}
    assert app_module._safe_json_value('{"ok": true}') == {"ok": True}
    assert app_module._safe_json_value("not-json") is None
    empty_summary = app_module._empty_analytics_summary("2026-01-01", "2026-01-31")
    assert empty_summary["range"] == {"from": "2026-01-01", "to": "2026-01-31"}
    assert empty_summary["success_rate"] == {"total": 0, "succeeded": 0, "rate": 0.0}
    model_usage = cast(dict[str, object], empty_summary["model_usage"])
    assert model_usage["estimate"] is True
    redacted = app_module._redact_payload({"nested": {"token": "x"}, "items": [{"bearer": "x"}]})
    nested = cast(dict[str, object], redacted["nested"])
    assert nested["token"] == "[redacted]"
    assert redacted["items"] == [{"bearer": "[redacted]"}]

    assert app_module._safe_json_list('[{"id": 1}, "ignored", 3]') == [{"id": 1}]
    assert app_module._safe_json_list("not-json") == []
    assert app_module._safe_json_list('{"id": 1}') == []
    assert app_module._safe_json_values('[{"id": 1}, 2]') == [{"id": 1}, 2]
    assert app_module._safe_json_values("not-json") == []
    assert app_module._safe_json_values('{"id": 1}') == []
    assert app_module._redact_json_text('{"api_key": "secret", "ok": true}') == (
        '{"api_key":"[redacted]","ok":true}'
    )
    assert app_module._redact_json_text("not-json") == "[redacted]"
    assert app_module._safe_redacted_json_object('{"token": "secret"}') == {"token": "[redacted]"}
    assert scheduled_jobs_module._scheduled_ticket_id({"ticket_id": " TCK-1 "}) == " TCK-1 "
    invalid_params: tuple[dict[str, object], ...] = ({}, {"ticket_id": " "}, {"ticket_id": 1})
    for params in invalid_params:
        with pytest.raises(HTTPException, match="include ticket_id"):
            scheduled_jobs_module._scheduled_ticket_id(params)

    assert app_module._redact_request_input(
        {"license": "secret", "nested": [{"value": "x"}]}, {"license", "value"}
    ) == {
        "license": "[redacted]",
        "nested": [{"value": "[redacted]"}],
    }
    assert app_module._redact_request_input("plain", set()) == "plain"

    class ValidationStub(Exception):
        def errors(self):
            return [
                {"loc": ("body", "value"), "input": "secret", "msg": "bad", "type": "value_error"},
                {"loc": ("body", "other"), "input": {"license": "secret"}, "msg": "bad", "type": "value_error"},
                {"loc": ("body", "missing"), "msg": "bad", "type": "value_error"},
            ]

    request = Request({"type": "http", "method": "POST", "path": "/secrets", "headers": []})
    response = app_module._request_validation_error_handler(request, ValidationStub())
    body = json.loads(bytes(response.body))
    assert body["detail"][0]["input"] == "[redacted]"
    assert body["detail"][1]["input"] == {"license": "[redacted]"}
    assert "input" not in body["detail"][2]
    contract_response = app_module._founder_contract_error_handler(
        request, app_module.FounderPackContractError("contract rejected")
    )
    assert contract_response.status_code == 502
    assert json.loads(bytes(contract_response.body))["detail"] == "contract rejected"
    monkeypatch.setattr(app_module, "_rate_limit_exceeded_handler", lambda *_args: Response(status_code=429))
    assert app_module._rate_limit_handler(request, Exception()).status_code == 429
    unbound_technician = AuthContext(role=Role.TECHNICIAN, presented_token="tech-token")
    with pytest.raises(HTTPException, match="has no tenant"):
        scheduled_jobs_module._scheduled_job_for_context(Store(settings.data_path), 1, unbound_technician)
    with pytest.raises(HTTPException, match="has no tenant"):
        scheduled_jobs_module._scheduled_job_for_context(
            Store(settings.data_path), 1, AuthContext(role=Role.ADMIN, presented_token="admin")
        )


def test_approval_request_update_propagates_to_workflow_run(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = 'acme'")
    client = TestClient(create_app(secure_settings))

    run = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        headers=_auth("tech-token"),
        json={"ticket_id": "TCK-1002"},
    )
    approval_request_id = run.json()["approval_request_id"]

    approved = client.post(
        f"/approval-requests/{approval_request_id}",
        headers=_auth("admin-token"),
        json={"status": "approved", "comment": "ready"},
    )
    approved_runs = client.get("/workflow-runs", headers=_auth("tech-token"))
    second_run = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        headers=_auth("tech-token"),
        json={"ticket_id": "TCK-1002"},
    )
    rejected = client.post(
        f"/approval-requests/{second_run.json()['approval_request_id']}",
        headers=_auth("admin-token"),
        json={"status": "rejected", "comment": "needs changes"},
    )
    rejected_runs = client.get("/workflow-runs", headers=_auth("tech-token"))

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    approved_view = next(item for item in approved_runs.json() if item["id"] == run.json()["id"])
    assert approved_view["status"] == "approved"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    rejected_view = next(
        item for item in rejected_runs.json() if item["id"] == second_run.json()["id"]
    )
    assert rejected_view["status"] == "rejected"


def test_workflow_and_halopsa_missing_resources_return_404(settings) -> None:
    client = TestClient(create_app(settings))

    missing_template = client.post(
        "/workflows/templates/nope/runs",
        json={"ticket_id": "TCK-1002"},
    )
    unsupported_action = client.post(
        "/connectors/halopsa/tickets/NOPE/drafts",
        json={"action_type": "unsupported", "fields": {"note": "Draft"}},
    )
    missing_approval = client.post(
        "/approval-requests/999",
        json={"status": "approved"},
    )

    assert missing_template.status_code == 404
    assert unsupported_action.status_code == 422
    assert missing_approval.status_code == 404


def test_halopsa_api_read_surfaces_block_without_http_flag(settings) -> None:
    client = TestClient(create_app(settings))

    health = client.get("/connectors/halopsa/health")
    tickets = client.get("/connectors/halopsa/tickets")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "blocked"
    assert tickets.status_code == 200
    assert tickets.json()["result"]["status"] == "blocked"
    assert tickets.json()["items"] == []
    assert any(event["event_type"] == "halopsa.read" for event in audit.json())


def test_halopsa_api_read_surfaces_missing_credentials(settings) -> None:
    configured_settings = settings.__class__(
        **{
            **settings.__dict__,
            "allow_http_probing": True,
            "halopsa_base_url": "https://halo.example.test",
            "halopsa_client_id": "client-id",
        }
    )
    client = TestClient(create_app(configured_settings))

    response = client.get("/connectors/halopsa/tickets")

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "not_configured"
    assert "WAIT_HALOPSA_CLIENT_SECRET" in response.json()["result"]["message"]


def test_connector_list_marks_configured_halopsa_as_blocked_until_http_enabled(settings) -> None:
    blocked_settings = settings.__class__(
        **{
            **settings.__dict__,
            "halopsa_base_url": "https://halo.example.test",
            "halopsa_client_id": "client-id",
            "halopsa_client_secret": "secret",
            "halopsa_tenant": "tenant",
        }
    )
    enabled_settings = blocked_settings.__class__(
        **{
            **blocked_settings.__dict__,
            "allow_http_probing": True,
        }
    )

    blocked = TestClient(create_app(blocked_settings)).get("/connectors")
    enabled = TestClient(create_app(enabled_settings)).get("/connectors")

    assert blocked.json()[0]["status"] == "blocked"
    assert enabled.json()[0]["status"] == "configured"


def test_halopsa_api_returns_normalized_mocked_reads(settings, monkeypatch) -> None:
    class FakeHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return HaloReadResult("ready", "ok", 0)

        def write_health(self):
            return HaloReadResult("ready", "write ok", 0)

        def list_tickets(self, page: int = 1, page_size: int = 50):
            assert page == 2
            assert page_size == 10
            return _read_response(
                [
                    HaloTicket(
                        id="TCK-1",
                        summary="Printer offline",
                        status="Open",
                        priority="High",
                        client_id="C-1",
                        client_name="Contoso",
                    )
                ]
            )

        def get_ticket(self, ticket_id: str):
            return _read_response([HaloTicket(ticket_id, "One", "Open", "Low", "C-1", "Contoso")])

        def list_ticket_notes(self, ticket_id: str):
            return _read_response([])

        def list_clients(self, page: int = 1, page_size: int = 50):
            return _read_response([])

        def list_client_assets(self, client_id: str):
            return _read_response([])

        def list_categories(self):
            return _read_response([])

    monkeypatch.setattr(app_module, "HaloPSAClient", FakeHaloClient)
    client = TestClient(app_module.create_app(settings))

    health = client.get("/connectors/halopsa/health")
    tickets = client.get("/connectors/halopsa/tickets", params={"page": 2, "page_size": 10})
    ticket = client.get("/connectors/halopsa/tickets/TCK-1")
    notes = client.get("/connectors/halopsa/tickets/TCK-1/notes")
    clients = client.get("/connectors/halopsa/clients")
    assets = client.get("/connectors/halopsa/clients/C-1/assets")
    categories = client.get("/connectors/halopsa/categories")

    assert health.json()["status"] == "ready"
    assert tickets.json()["items"][0]["id"] == "TCK-1"
    assert ticket.json()["items"][0]["summary"] == "One"
    assert notes.json()["result"]["status"] == "ready"
    assert clients.json()["result"]["status"] == "ready"
    assert assets.json()["result"]["status"] == "ready"
    assert categories.json()["result"]["status"] == "ready"


def test_halopsa_draft_can_target_remote_ticket_and_auto_executes(
    settings, monkeypatch
) -> None:
    executed = []

    class FakeHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def execute_write(self, request):
            executed.append(request)
            return HaloWriteResult(
                "succeeded",
                "posted",
                request.action_type,
                request.ticket_id,
                endpoint="Actions",
                status_code=200,
                remote_id="A-1",
            )

        def verify_write(
            self,
            request: HaloWriteRequest,
            write_result: HaloWriteResult,
            *,
            detail: dict[str, object] | None = None,
        ) -> Literal["verified", "unverified", "submitted"]:
            return "verified"

    monkeypatch.setattr(app_module, "HaloPSAClient", FakeHaloClient)
    client = TestClient(app_module.create_app(settings))

    draft = client.post(
        "/connectors/halopsa/tickets/HALO-42/drafts",
        json={"action_type": "add_note", "fields": {"note": "Remote ticket note"}},
    )
    approved = client.post(
        f"/approval-requests/{draft.json()['approval_request_id']}",
        json={"status": "approved", "comment": "ship"},
    )
    events = client.get("/event-history")

    assert draft.status_code == 200
    assert approved.status_code == 200
    assert approved.json()["execution_status"] == "verified"
    assert approved.json()["execution_result_json"]
    assert executed[0].ticket_id == "HALO-42"
    assert any(event["event_type"] == "halopsa.write" for event in events.json())


def test_m365_write_actions_require_admin_at_invoke_boundary(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "client_id": "acme",
        }
    )
    client = TestClient(create_app(secure_settings))

    for action_id, payload in (
        (
            "m365-user-offboarding",
            {"user_identity": "user@example.test", "user_id": "graph-user-1"},
        ),
        (
            "m365-user-onboarding",
            {
                "user_principal_name": "user@example.test",
                "display_name": "User Example",
                "mail_nickname": "user.example",
                "temporary_vault_name": "WAIT_M365_TEMP_USER",
            },
        ),
        (
            "m365-group-membership",
            {
                "group_id": "group-immutable-id",
                "user_id": "user-immutable-id",
                "operation": "add",
            },
        ),
        (
            "m365-license-change",
            {
                "user_id": "user-immutable-id",
                "sku_ids": ["00000000-0000-0000-0000-000000000001"],
                "operation": "add",
            },
        ),
        (
            "m365-session-revocation",
            {"user_id": "user-immutable-id"},
        ),
        (
            "m365-mailbox-settings",
            {
                "user_identity": "user@example.test",
                "settings": {"locale": "en-US"},
            },
        ),
        (
            "m365-mail-message-move",
            {
                "user_identity": "user@example.test",
                "source_folder_id": "inbox-id",
                "message_id": "message-id",
                "destination_folder_id": "archive-id",
            },
        ),
        (
            "m365-mail-message-read-state",
            {
                "user_identity": "user@example.test",
                "source_folder_id": "inbox-id",
                "message_id": "message-id",
                "is_read": True,
            },
        ),
        (
            "m365-mail-message-delete",
            {
                "user_identity": "user@example.test",
                "source_folder_id": "inbox-id",
                "message_id": "message-id",
            },
        ),
        (
            "m365-managed-device-reboot",
            {"device_id": "device-1"},
        ),
        (
            "m365-managed-device-remote-lock",
            {"device_id": "device-1"},
        ),
        (
            "m365-managed-device-retire",
            {"device_id": "device-1"},
        ),
        (
            "m365-managed-device-sync",
            {"device_id": "device-1"},
        ),
    ):
        denied = client.post(
            f"/smart-actions/{action_id}/invoke",
            headers=_auth("tech-token"),
            json={"client_id": "acme", "payload": payload},
        )
        detail = client.get(f"/smart-actions/{action_id}", headers=_auth("tech-token"))

        assert denied.status_code == 403
        assert detail.status_code == 200
        assert detail.json()["required_role"] == "admin"


def test_connectwise_approval_gated_ticket_update_routes(settings, monkeypatch) -> None:
    class FakeConnectWiseClient:
        def __init__(self, _settings) -> None:
            self.executed: list[object] = []

        def health(self):
            return ConnectorReadResult("ready", "ConnectWise ready", 0)

        def write_health(self):
            return ConnectorReadResult("ready", "ConnectWise writes ready", 0)

        def execute_write(self, request):
            self.executed.append(request)
            return ConnectWiseWriteResult(
                "succeeded", "updated", request.action_type, request.ticket_id,
                endpoint="service/tickets/42", status_code=200, remote_id="42"
            )

        def verify_write(
            self,
            request: ConnectWiseWriteRequest,
            write_result: ConnectWiseWriteResult,
            *,
            detail: dict[str, object] | None = None,
        ) -> Literal["verified", "unverified", "submitted"]:
            return "submitted"

        def list_tickets(self, **kwargs):
            return ConnectWiseReadResponse(ConnectorReadResult("ready", "ok", 0), [])

        def get_ticket(self, ticket_id):
            return ConnectWiseReadResponse(ConnectorReadResult("ready", "ok", 0), [])

        def list_companies(self, **kwargs):
            return ConnectWiseReadResponse(ConnectorReadResult("ready", "ok", 0), [])

    monkeypatch.setattr(app_module, "ConnectWiseClient", FakeConnectWiseClient)
    client = TestClient(create_app(settings))

    draft = client.post(
        "/connectors/connectwise/tickets/42/drafts",
        json={"action_type": "update_status", "fields": {"status_id": 7}, "client_id": "acme"},
    )
    assert draft.status_code == 200
    request_id = draft.json()["approval_request_id"]
    assert draft.json()["payload"]["connector"] == "connectwise"
    assert draft.json()["payload"]["fields"] == {"status_id": 7}
    edited = client.patch(
        f"/approval-requests/{request_id}/payload",
        json={"fields": {"status_id": 8}, "comment": "reviewed"},
    )

    write_health = client.get("/connectors/connectwise/write-health")
    approved = client.post(
        f"/approval-requests/{request_id}",
        json={"status": "approved", "comment": "approved"},
    )
    audit = client.get("/audit")

    assert write_health.json()["status"] == "ready"
    assert edited.status_code == 200
    assert edited.json()["payload"]["fields"] == {"status_id": 8}
    assert approved.status_code == 200
    assert approved.json()["execution_status"] == "submitted"
    assert any(event["event_type"] == "connectwise.write" for event in audit.json())


def test_knowledge_api_missing_path_returns_400(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": "examples/sample_docs/missing.md"})

    assert response.status_code == 400



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
            raise app_module.ClientDiscoveryError("provider unavailable")
        return [candidate]

    monkeypatch.setattr(app_module, "discover_instance", fake_discover)
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
        app_module.AllClients(), instance.connector_instance_id, "already-mapped", "other"
    )
    store.verify_client_connector_mapping(app_module.AllClients(), existing_mapping.mapping_id)
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
        app_module.AllClients(), instance.connector_instance_id, "already-linked", "other"
    )
    store.verify_client_connector_mapping(app_module.AllClients(), existing_mapping.mapping_id)
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
