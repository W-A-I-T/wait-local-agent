from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.collectors import (
    default_registry,
)
from wait_local_agent.connectwise import ConnectWiseReadResponse
from wait_local_agent.models import (
    ConnectorReadResult,
    HaloReadResult,
    HaloTicket,
    HaloWriteResult,
    HuduArticle,
    HuduCompany,
    HuduFolder,
)
from wait_local_agent.servicenow import ServiceNowReadResponse
from wait_local_agent.store import Store
from wait_local_agent.syncro import SyncroReadResponse


def test_api_lists_exactly_fourteen_collector_modules(settings, isolated_default_registry) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/collectors/modules")

    assert response.status_code == 200
    modules = response.json()
    registered_ids = [module.manifest.id for module in default_registry.list()]
    assert [module["id"] for module in modules] == registered_ids
    assert len(modules) == len(registered_ids) == 14


def test_health_reports_safe_defaults(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["write_actions_enabled"] is False
    assert response.json()["http_probing_enabled"] is False
    assert response.json()["cloud_fallback_enabled"] is False
    assert response.json()["demo_mode"] is True
    assert response.json()["api_auth_required"] is False


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


def test_provider_settings_and_tickets_list(settings) -> None:
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    providers = client.get("/settings/providers")
    tickets = client.get("/tickets")

    assert providers.status_code == 200
    assert providers.json()["vector_backend"] == "sqlite"
    assert providers.json()["llm_inference_enabled"] is False
    assert providers.json()["local_model_timeout_seconds"] == 20.0
    assert tickets.status_code == 200
    assert len(tickets.json()) == 2


def test_ticket_summary_and_approval_flow(settings) -> None:
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    summary = client.get("/tickets/TCK-1001/summary")
    approval = client.post(
        "/tickets/TCK-1001/approvals",
        json={"status": "approved", "comment": "ship it"},
    )
    audit = client.get("/audit")

    assert summary.status_code == 200
    assert summary.json()["classification"] == "identity-access"
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"
    assert approval.json()["comment"] == "ship it"
    assert audit.status_code == 200
    assert any(event["event_type"] == "approval.updated" for event in audit.json())


def test_approval_missing_ticket_returns_404(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/tickets/NOPE/approvals", json={"status": "approved"})

    assert response.status_code == 404


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
    with store._connect() as connection:  # noqa: SLF001
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
    filtered_tickets = client.get("/tickets", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    filtered_approvals = client.get("/approval-requests", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    narrowed_approvals = client.get("/approval-requests", params={"client_id": "beta"}, headers=_auth("viewer-token"))
    filtered_audit = client.get("/audit", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    filtered_documents = client.get("/knowledge/documents", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    filtered_runs = client.get("/workflow-runs", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    ticket_approval = client.post(
        "/tickets/TCK-ACME/approvals",
        headers=_auth("tech-token"),
        json={"status": "approved", "comment": "ship it"},
    )
    approved = client.post(
        f"/approval-requests/{approval.id}",
        headers=_auth("tech-token"),
        json={"status": "approved", "comment": "ship it"},
    )
    export = client.get("/audit-events/export", params={"client_id": "acme"}, headers=_auth("admin-token"))
    expected_approver_id = hashlib.sha256(b"tech-token").hexdigest()[:16]

    assert role.status_code == 200
    assert role.json()["role"] == "viewer"
    assert [ticket["id"] for ticket in filtered_tickets.json()] == ["TCK-ACME"]
    assert [request["subject_id"] for request in filtered_approvals.json()] == ["TCK-ACME"]
    assert [request["subject_id"] for request in narrowed_approvals.json()] == ["TCK-BETA"]
    assert all(event["client_id"] == "acme" for event in filtered_audit.json())
    assert [document["title"] for document in filtered_documents.json()] == ["Acme"]
    assert [run["ticket_id"] for run in filtered_runs.json()] == ["TCK-ACME"]
    assert ticket_approval.status_code == 200
    assert approved.status_code == 200
    assert approved.json()["approver_id"] == expected_approver_id
    assert any(
        event["event_type"] == "approval.updated" and event["client_id"] == "acme"
        for event in client.get("/audit", params={"client_id": "acme"}, headers=_auth("viewer-token")).json()
    )
    assert any(
        event["event_type"] == "approval_request.updated" and event["approver_id"] == expected_approver_id
        for event in export.json()["events"]
    )


def test_approval_requests_are_scoped_to_authenticated_tenant(settings, monkeypatch) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    acme = store.create_approval_request(
        "TCK-ACME",
        "ticket.assign",
        {"ticket_id": "TCK-ACME"},
        client_id="acme",
    )
    globex = store.create_approval_request(
        "TCK-GLOBEX",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "TCK-GLOBEX",
            "action_type": "add_note",
            "fields": {"note": "original"},
        },
        client_id="globex",
    )
    legacy = store.create_approval_request(
        "TCK-LEGACY",
        "ticket.assign",
        {"ticket_id": "TCK-LEGACY"},
    )
    acme_halopsa = store.create_approval_request(
        "TCK-ACME-HALO",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "TCK-ACME-HALO",
            "action_type": "add_note",
            "fields": {"note": "ready"},
        },
        client_id="acme",
    )
    store.update_approval_request(acme_halopsa.id or 0, "approved")
    execute_calls: list[int] = []

    def fake_execute(store_arg, _client, request_id: int):
        execute_calls.append(request_id)
        return store_arg.get_approval_request(request_id)

    monkeypatch.setattr(app_module, "execute_halopsa_approval_request", fake_execute)
    client = TestClient(create_app(secure_settings))

    scoped_list = client.get(
        "/approval-requests",
        params={"client_id": "globex"},
        headers=_auth("tech-token"),
    )
    foreign_detail = client.get(f"/approval-requests/{globex.id}", headers=_auth("tech-token"))
    foreign_patch = client.patch(
        f"/approval-requests/{globex.id}/payload",
        headers=_auth("tech-token"),
        json={"fields": {"note": "tampered"}},
    )
    foreign_update = client.post(
        f"/approval-requests/{globex.id}",
        headers=_auth("tech-token"),
        json={"status": "approved", "comment": "tampered"},
    )
    foreign_execute = client.post(
        f"/connectors/halopsa/approval-requests/{globex.id}/execute",
        headers=_auth("tech-token"),
    )
    foreign_after_technician = store.get_approval_request(globex.id or 0)
    acme_detail = client.get(f"/approval-requests/{acme.id}", headers=_auth("tech-token"))
    acme_update = client.post(
        f"/approval-requests/{acme.id}",
        headers=_auth("tech-token"),
        json={"status": "approved", "comment": "approved"},
    )
    legacy_detail = client.get(f"/approval-requests/{legacy.id}", headers=_auth("tech-token"))
    legacy_update = client.post(
        f"/approval-requests/{legacy.id}",
        headers=_auth("tech-token"),
        json={"status": "approved", "comment": "approved"},
    )
    acme_execute = client.post(
        f"/connectors/halopsa/approval-requests/{acme_halopsa.id}/execute",
        headers=_auth("tech-token"),
    )
    admin_list = client.get("/approval-requests", headers=_auth("admin-token"))
    admin_filtered = client.get(
        "/approval-requests",
        params={"client_id": "globex"},
        headers=_auth("admin-token"),
    )
    admin_detail = client.get(f"/approval-requests/{globex.id}", headers=_auth("admin-token"))
    admin_update = client.post(
        f"/approval-requests/{globex.id}",
        headers=_auth("admin-token"),
        json={"status": "rejected", "comment": "admin decision"},
    )

    assert [request["subject_id"] for request in scoped_list.json()] == [
        "TCK-ACME-HALO",
        "TCK-ACME",
    ]
    assert foreign_detail.status_code == 404
    assert foreign_patch.status_code == 404
    assert foreign_update.status_code == 404
    assert foreign_execute.status_code == 404
    assert execute_calls == [acme_halopsa.id]
    assert acme_detail.status_code == 200
    assert acme_update.status_code == 200
    assert legacy_detail.status_code == 200
    assert legacy_update.status_code == 200
    assert acme_execute.status_code == 200
    assert admin_list.status_code == 200
    assert {request["subject_id"] for request in admin_list.json()} == {
        "TCK-ACME",
        "TCK-GLOBEX",
        "TCK-LEGACY",
        "TCK-ACME-HALO",
    }
    assert [request["subject_id"] for request in admin_filtered.json()] == ["TCK-GLOBEX"]
    assert admin_detail.status_code == 200
    assert admin_update.status_code == 200
    assert foreign_after_technician is not None
    assert foreign_after_technician.status == "pending"
    assert foreign_after_technician.comment == ""
    foreign_after = store.get_approval_request(globex.id or 0)
    assert foreign_after is not None
    assert foreign_after.status == "rejected"
    assert foreign_after.comment == "admin decision"
    assert foreign_after.payload_json == globex.payload_json


def test_workflow_run_detail_hides_foreign_approval_payload(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    foreign_approval = store.create_approval_request(
        "TCK-GLOBEX",
        "ticket.assign",
        {"ticket_id": "TCK-GLOBEX", "payload": "foreign"},
        client_id="globex",
    )
    local_approval = store.create_approval_request(
        "TCK-ACME",
        "ticket.assign",
        {"ticket_id": "TCK-ACME", "payload": "local"},
        client_id="acme",
    )
    foreign_run = store.create_workflow_run(
        "documentation-assisted-response",
        "TCK-GLOBEX",
        "pending_approval",
        "foreign approval link",
        foreign_approval.id,
        client_id="acme",
    )
    local_run = store.create_workflow_run(
        "documentation-assisted-response",
        "TCK-ACME",
        "pending_approval",
        "local approval link",
        local_approval.id,
        client_id="acme",
    )
    client = TestClient(create_app(secure_settings))

    foreign_response = client.get(f"/workflow-runs/{foreign_run.id}", headers=_auth("tech-token"))
    local_response = client.get(f"/workflow-runs/{local_run.id}", headers=_auth("tech-token"))

    assert foreign_response.status_code == 200
    foreign_payload = foreign_response.json()
    assert foreign_payload["approval_request"] is None
    assert foreign_payload["id"] == foreign_run.id
    assert foreign_payload["template_id"] == foreign_run.template_id
    assert foreign_payload["ticket_id"] == foreign_run.ticket_id
    assert foreign_payload["status"] == foreign_run.status
    assert foreign_payload["message"] == foreign_run.message
    assert foreign_payload["approval_request_id"] == foreign_approval.id
    assert foreign_payload["client_id"] == foreign_run.client_id
    assert foreign_payload["created_at"] == foreign_run.created_at
    assert foreign_payload["updated_at"] == foreign_run.updated_at
    assert foreign_payload["template"]["id"] == foreign_run.template_id
    assert isinstance(foreign_payload["events"], list)

    assert local_response.status_code == 200
    local_payload = local_response.json()
    assert local_payload["approval_request"]["id"] == local_approval.id
    assert local_payload["approval_request"]["client_id"] == "acme"
    assert local_payload["approval_request"]["payload"] == {
        "ticket_id": "TCK-ACME",
        "payload": "local",
    }
    assert local_payload["approval_request"]["workflow_run_id"] == local_run.id


def test_bound_technician_can_patch_in_scope_approval_payload(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    approval = store.create_approval_request(
        "TCK-ACME",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "TCK-ACME",
            "action_type": "add_note",
            "fields": {"note": "before"},
        },
        client_id="acme",
    )
    client = TestClient(create_app(secure_settings))

    response = client.patch(
        f"/approval-requests/{approval.id}/payload",
        headers=_auth("tech-token"),
        json={"fields": {"note": "after"}, "comment": "updated in scope"},
    )

    assert response.status_code == 200
    assert response.json()["client_id"] == "acme"
    assert response.json()["payload"]["fields"] == {"note": "after"}
    assert response.json()["comment"] == "updated in scope"
    persisted = store.get_approval_request(approval.id or 0)
    assert persisted is not None
    assert persisted.status == "pending"
    assert persisted.client_id == "acme"


def test_bound_non_admin_approval_list_without_filter_is_tenant_scoped(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    store.create_approval_request(
        "TCK-ACME",
        "ticket.assign",
        {"ticket_id": "TCK-ACME"},
        client_id="acme",
    )
    store.create_approval_request(
        "TCK-GLOBEX",
        "ticket.assign",
        {"ticket_id": "TCK-GLOBEX"},
        client_id="globex",
    )
    client = TestClient(create_app(secure_settings))

    response = client.get("/approval-requests", headers=_auth("tech-token"))

    assert response.status_code == 200
    assert [request["subject_id"] for request in response.json()] == ["TCK-ACME"]


def test_missing_ticket_returns_404(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/tickets/DOES-NOT-EXIST/summary")

    assert response.status_code == 404


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
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
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
    assert secrets.status_code == 200
    assert any(secret["key"] == "WAIT_HALOPSA_BASE_URL" for secret in secrets.json())
    assert any(secret["key"] == "WAIT_HUDU_API_KEY" for secret in secrets.json())
    assert templates.status_code == 200
    assert len(templates.json()) == 5
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


def test_workflow_run_inherits_ticket_client_id_when_request_omits_it(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1002"),
        )
    client = TestClient(create_app(settings))

    run = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        json={"ticket_id": "TCK-1002"},
    )
    approvals = client.get("/approval-requests", params={"client_id": "acme"})
    runs = client.get("/workflow-runs", params={"client_id": "acme"})

    assert run.status_code == 200
    assert run.json()["client_id"] == "acme"
    assert [request["subject_id"] for request in approvals.json()] == ["TCK-1002"]
    assert [item["ticket_id"] for item in runs.json()] == ["TCK-1002"]


def test_scheduled_job_inherits_ticket_client_id_when_request_omits_it(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "scheduler_enabled": True,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    client = TestClient(create_app(secure_settings))

    created = client.post(
        "/scheduled-jobs",
        headers=_auth("tech-token"),
        json={
            "template_id": "documentation-assisted-response",
            "cron": "0 9 * * *",
            "params": {"ticket_id": "TCK-1001"},
        },
    )
    filtered = client.get(
        "/scheduled-jobs",
        params={"client_id": "acme"},
        headers=_auth("viewer-token"),
    )

    assert created.status_code == 200
    assert created.json()["client_id"] == "acme"
    assert created.json()["params"]["client_id"] == "acme"
    assert [job["id"] for job in filtered.json()] == [created.json()["id"]]


def test_scheduled_job_inherits_ticket_client_id_when_request_has_blank_client_id(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "scheduler_enabled": True,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1001"),
        )
    client = TestClient(create_app(secure_settings))

    blank = client.post(
        "/scheduled-jobs",
        headers=_auth("tech-token"),
        json={
            "template_id": "documentation-assisted-response",
            "cron": "0 9 * * *",
            "params": {"ticket_id": "TCK-1001", "client_id": ""},
        },
    )
    nullish = client.post(
        "/scheduled-jobs",
        headers=_auth("tech-token"),
        json={
            "template_id": "documentation-assisted-response",
            "cron": "15 9 * * *",
            "params": {"ticket_id": "TCK-1001", "client_id": None},
        },
    )
    filtered = client.get(
        "/scheduled-jobs",
        params={"client_id": "acme"},
        headers=_auth("viewer-token"),
    )

    assert blank.status_code == 200
    assert nullish.status_code == 200
    assert blank.json()["client_id"] == "acme"
    assert blank.json()["params"]["client_id"] == "acme"
    assert nullish.json()["client_id"] == "acme"
    assert nullish.json()["params"]["client_id"] == "acme"
    assert [job["id"] for job in filtered.json()] == [nullish.json()["id"], blank.json()["id"]]


def test_invalid_halopsa_draft_returns_400(settings, monkeypatch) -> None:
    client = TestClient(create_app(settings))

    def fail_draft(*args, **kwargs):
        raise ValueError("bad draft")

    monkeypatch.setattr(app_module, "draft_halopsa_ticket_action", fail_draft)

    response = client.post(
        "/connectors/halopsa/tickets/TCK-1002/drafts",
        json={"action_type": "add_note", "fields": {"note": "ok"}},
    )

    assert response.status_code == 400


def test_approval_detail_handles_invalid_payload_and_missing_write_health(settings, monkeypatch) -> None:
    class HaloClientWithoutWriteHealth:
        def __init__(self, _settings) -> None:
            pass

    store = Store(settings.data_path)
    approval = store.create_approval_request(
        "TCK-1002",
        "halopsa.add_note",
        {"fields": {"note": "ok"}},
    )
    store.update_approval_request(approval.id or 0, "approved", "ready")
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update approval_requests set payload_json = ? where id = ?",
            ("not-json", approval.id),
        )
    monkeypatch.setattr(app_module, "HaloPSAClient", HaloClientWithoutWriteHealth)
    client = TestClient(app_module.create_app(settings))

    response = client.get(f"/approval-requests/{approval.id}")

    assert response.status_code == 200
    assert response.json()["payload"] == {}
    assert response.json()["block_reason"] == "HaloPSA write health is unavailable."


def test_update_approval_request_recovers_from_runtime_error(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    approval = store.create_approval_request(
        "TCK-1002",
        "halopsa.add_note",
        {"fields": {"note": "ok"}},
    )
    client = TestClient(create_app(settings))

    def fail_execution(_store, _client, request_id: int):
        raise RuntimeError(f"execution failed for {request_id}")

    monkeypatch.setattr(app_module, "execute_halopsa_approval_request", fail_execution)
    response = client.post(
        f"/approval-requests/{approval.id}",
        json={"status": "approved", "comment": "try later"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["execution_status"] == "not_started"


def test_scheduled_job_api_validation_and_missing_jobs(settings) -> None:
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    missing_template = client.post(
        "/scheduled-jobs",
        json={"template_id": "missing", "cron": "0 1 * * *", "params": {"ticket_id": "TCK-1002"}},
    )
    missing_ticket = client.post(
        "/scheduled-jobs",
        json={"template_id": "documentation-assisted-response", "cron": "0 1 * * *", "params": {"ticket_id": "NOPE"}},
    )
    missing_param = client.post(
        "/scheduled-jobs",
        json={"template_id": "documentation-assisted-response", "cron": "0 1 * * *", "params": {}},
    )
    pause = client.post("/scheduled-jobs/999/pause")
    resume = client.post("/scheduled-jobs/999/resume")
    reschedule = client.post("/scheduled-jobs/999/reschedule", json={"cron": "0 2 * * *"})
    delete = client.delete("/scheduled-jobs/999")

    assert missing_template.status_code == 404
    assert missing_ticket.status_code == 404
    assert missing_param.status_code == 422
    assert pause.status_code == 404
    assert resume.status_code == 404
    assert reschedule.status_code == 404
    assert delete.status_code == 404


def test_approval_detail_payload_edit_and_workflow_detail(settings) -> None:
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))
    draft = client.post(
        "/connectors/halopsa/tickets/TCK-1002/drafts",
        json={"action_type": "add_note", "fields": {"note": "Original"}},
    )
    request_id = draft.json()["approval_request_id"]

    detail = client.get(f"/approval-requests/{request_id}")
    edited = client.patch(
        f"/approval-requests/{request_id}/payload",
        json={"fields": {"note": "Edited"}, "comment": "edited before approval"},
    )
    approved = client.post(
        f"/approval-requests/{request_id}",
        json={"status": "approved", "comment": "ready"},
    )
    rejected_edit = client.patch(
        f"/approval-requests/{request_id}/payload",
        json={"fields": {"note": "Too late"}},
    )
    events = client.get("/event-history")

    assert detail.status_code == 200
    assert detail.json()["payload"]["fields"]["note"] == "Original"
    assert detail.json()["block_reason"] == "Approval must be approved before execution."
    assert edited.status_code == 200
    assert edited.json()["payload"]["fields"]["note"] == "Edited"
    assert approved.status_code == 200
    assert rejected_edit.status_code == 409
    assert any(event["event_type"] == "approval_request.edited" for event in events.json())

    workflow = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        json={"ticket_id": "TCK-1002"},
    )
    workflow_detail = client.get(f"/workflow-runs/{workflow.json()['id']}")

    assert workflow_detail.status_code == 200
    assert workflow_detail.json()["template"]["risk_level"] == "medium"
    assert workflow_detail.json()["approval_request"]["workflow_run_id"] == workflow.json()["id"]


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
    redacted = app_module._redact_payload({"nested": {"token": "x"}, "items": [{"bearer": "x"}]})
    nested = cast(dict[str, object], redacted["nested"])
    assert nested["token"] == "[redacted]"
    assert redacted["items"] == [{"bearer": "[redacted]"}]


def test_approval_request_update_propagates_to_workflow_run(settings) -> None:
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    run = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        json={"ticket_id": "TCK-1002"},
    )
    approval_request_id = run.json()["approval_request_id"]

    approved = client.post(
        f"/approval-requests/{approval_request_id}",
        json={"status": "approved", "comment": "ready"},
    )
    approved_runs = client.get("/workflow-runs")
    rejected = client.post(
        f"/approval-requests/{approval_request_id}",
        json={"status": "rejected", "comment": "needs changes"},
    )
    rejected_runs = client.get("/workflow-runs")

    assert approved.status_code == 200
    assert approved_runs.json()[0]["status"] == "approved"
    assert rejected.status_code == 200
    assert rejected_runs.json()[0]["status"] == "rejected"


def test_scheduled_job_routes_cover_rbac_validation_and_live_scheduler_registration(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "scheduler_enabled": True,
            "client_id": "acme",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")

    app = create_app(secure_settings)

    with TestClient(app) as client:
        viewer_create = client.post(
            "/scheduled-jobs",
            headers=_auth("viewer-token"),
            json={
                "template_id": "documentation-assisted-response",
                "cron": "0 9 * * *",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        invalid_cron = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "cron": "bad cron",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        created = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "cron": "0 9 * * *",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        listed = client.get("/scheduled-jobs", headers=_auth("viewer-token"))
        job_id = created.json()["id"]

        assert viewer_create.status_code == 403
        assert invalid_cron.status_code == 422
        assert "invalid cron expression" in invalid_cron.json()["detail"]
        assert created.status_code == 200
        assert created.json()["next_run_at"] is not None
        assert created.json()["params"]["ticket_id"] == "TCK-1001"
        assert app.state.scheduler._scheduler is not None
        assert len(app.state.scheduler._scheduler.get_jobs()) == 1
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == job_id

        interval = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "schedule_type": "interval",
                "interval_seconds": 60,
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        once = client.post(
            "/scheduled-jobs",
            headers=_auth("tech-token"),
            json={
                "template_id": "documentation-assisted-response",
                "schedule_type": "once",
                "run_at": "2099-01-01T00:00:00+00:00",
                "params": {"ticket_id": "TCK-1001", "client_id": "acme"},
            },
        )
        assert interval.status_code == 200
        assert interval.json()["schedule_type"] == "interval"
        assert interval.json()["interval_seconds"] == 60
        assert once.status_code == 200
        assert once.json()["schedule_type"] == "once"
        assert once.json()["run_at"] == "2099-01-01T00:00:00+00:00"

        rescheduled = client.post(
            f"/scheduled-jobs/{job_id}/reschedule",
            headers=_auth("tech-token"),
            json={"schedule_type": "interval", "interval_seconds": 120},
        )
        assert rescheduled.status_code == 200
        assert rescheduled.json()["schedule_type"] == "interval"
        assert rescheduled.json()["interval_seconds"] == 120
        paused = client.post(f"/scheduled-jobs/{job_id}/pause", headers=_auth("tech-token"))
        resumed = client.post(f"/scheduled-jobs/{job_id}/resume", headers=_auth("tech-token"))
        rescheduled = client.post(
            f"/scheduled-jobs/{job_id}/reschedule",
            headers=_auth("tech-token"),
            json={"schedule_type": "interval", "interval_seconds": 120},
        )
        invalid_reschedule = client.post(
            f"/scheduled-jobs/{job_id}/reschedule",
            headers=_auth("tech-token"),
            json={"cron": "bad cron"},
        )
        deleted = client.delete(f"/scheduled-jobs/{job_id}", headers=_auth("tech-token"))

        assert paused.status_code == 200
        assert paused.json()["paused"] is True
        assert paused.json()["next_run_at"] is None
        assert resumed.status_code == 200
        assert resumed.json()["paused"] is False
        assert resumed.json()["next_run_at"] is not None
        assert rescheduled.status_code == 200
        assert rescheduled.json()["schedule_type"] == "interval"
        assert rescheduled.json()["interval_seconds"] == 120
        assert invalid_reschedule.status_code == 422
        assert deleted.status_code == 200
        assert deleted.json()["id"] == job_id
        assert client.delete(
            f"/scheduled-jobs/{interval.json()['id']}", headers=_auth("tech-token")
        ).status_code == 200
        assert client.delete(
            f"/scheduled-jobs/{once.json()['id']}", headers=_auth("tech-token")
        ).status_code == 200
        assert len(app.state.scheduler._scheduler.get_jobs()) == 0
        assert client.get("/scheduled-jobs", headers=_auth("viewer-token")).json() == []


def test_scheduled_agent_route_requires_scheduled_definition_and_persists_target(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    created = client.post(
        "/agents",
        json={
            "name": "Scheduled triage",
            "trigger": "scheduled",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]

    scheduled = client.post(
        "/scheduled-jobs",
        json={
            "agent_id": agent_id,
            "entity_id": "TCK-1001",
            "cron": "0 9 * * *",
            "params": {"client_id": "acme", "input": {"instruction": "triage"}},
        },
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["job_kind"] == "agent"
    assert scheduled.json()["agent_id"] == agent_id
    assert scheduled.json()["entity_id"] == "TCK-1001"

    manual = client.post(
        "/agents",
        json={
            "name": "Manual triage",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert manual.status_code == 200
    rejected = client.post(
        "/scheduled-jobs",
        json={
            "agent_id": manual.json()["id"],
            "entity_id": "TCK-1001",
            "cron": "0 9 * * *",
            "params": {"client_id": "acme"},
        },
    )
    assert rejected.status_code == 422


def test_event_ingest_route_dispatches_idempotently_and_exposes_delivery_history(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    agent = client.post(
        "/agents",
        json={
            "name": "Created P1 triage",
            "trigger": "event",
            "filters": {"event_type": "ticket.created", "priority": "P1"},
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert agent.status_code == 200

    event = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-event-1"},
        json={
            "event_type": "ticket.created",
            "entity_id": "TCK-1001",
            "client_id": "acme",
            "payload": {"priority": "P1", "api_token": "secret-value"},
        },
    )
    assert event.status_code == 200
    assert event.json()["duplicate"] is False
    assert event.json()["delivery"]["status"] == "completed"
    assert event.json()["run_ids"]
    assert "secret-value" not in event.text

    duplicate = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-event-1"},
        json={
            "event_type": "ticket.created",
            "entity_id": "TCK-1001",
            "client_id": "acme",
            "payload": {"priority": "P1"},
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    deliveries = client.get("/automation/event-deliveries")
    assert deliveries.status_code == 200
    assert deliveries.json()[0]["idempotency_key"] == "api-event-1"
    detail = client.get(f"/automation/event-deliveries/{deliveries.json()[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["event_type"] == "ticket.created"

    missing_key = client.post(
        "/automation/events",
        json={"event_type": "ticket.created", "entity_id": "TCK-1001"},
    )
    assert missing_key.status_code == 422

    unsupported = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-unsupported-event"},
        json={"event_type": "ticket.deleted", "entity_id": "TCK-1001"},
    )
    assert unsupported.status_code == 422

    missing_entity = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-missing-entity"},
        json={"event_type": "ticket.created", "entity_id": "NO-SUCH-TICKET"},
    )
    assert missing_entity.status_code == 404
    missing_delivery = client.get("/automation/event-deliveries/99999")
    assert missing_delivery.status_code == 404


def test_template_gallery_is_provenance_bearing_and_runs_only_in_scope(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    created = client.post(
        "/workflow-templates/gallery",
        json={
            "source_template_id": "ticket-triage",
            "display_name": "Acme triage starter",
            "provenance": "Reviewed by the local operator",
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    assert created.json()["source_template_id"] == "ticket-triage"
    assert created.json()["provenance"] == "Reviewed by the local operator"
    entry_id = created.json()["id"]

    listed = client.get("/workflow-templates/gallery")
    detail = client.get(f"/workflow-templates/gallery/{entry_id}")
    assert listed.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["id"] == entry_id

    run = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert run.status_code == 200
    assert run.json()["template_id"] == "ticket-triage"
    assert run.json()["status"] == "completed"

    unknown_source = client.post(
        "/workflow-templates/gallery",
        json={"source_template_id": "not-a-template", "provenance": "review"},
    )
    foreign_run = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "beta"},
    )
    missing_entry = client.get("/workflow-templates/gallery/not-a-gallery-entry")
    missing_ticket = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "NO-SUCH-TICKET", "client_id": "acme"},
    )
    assert unknown_source.status_code == 404
    assert foreign_run.status_code == 404
    assert missing_entry.status_code == 404
    assert missing_ticket.status_code == 404

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    secure_client = TestClient(create_app(secure))
    assert secure_client.get(
        "/workflow-templates/gallery",
        headers=_auth("viewer-token"),
    ).json() == []
    assert secure_client.get(
        "/workflow-templates/gallery/anything",
        headers=_auth("viewer-token"),
    ).status_code == 404
    assert secure_client.post(
        "/workflow-templates/gallery",
        headers=_auth("tech-token"),
        json={"source_template_id": "ticket-triage", "provenance": "review"},
    ).status_code == 403
    assert secure_client.post(
        "/workflow-templates/gallery/anything/runs",
        headers=_auth("tech-token"),
        json={"ticket_id": "TCK-1001"},
    ).status_code == 403


def test_bounded_agent_backfill_supports_pause_cancel_and_failed_reruns(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    agent = client.post(
        "/agents",
        json={
            "name": "Backfill triage",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert agent.status_code == 200
    agent_id = agent.json()["id"]

    created = client.post(
        "/agent-backfills",
        json={
            "agent_id": agent_id,
            "entity_ids": ["TCK-1001", "TCK-1002"],
            "input": {"api_token": "backfill-secret"},
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "queued"
    assert "backfill-secret" not in created.text
    backfill_id = created.json()["id"]
    assert client.get("/agent-backfills").json()[0]["id"] == backfill_id
    assert client.get(f"/agent-backfills/{backfill_id}").status_code == 200

    paused = client.post(f"/agent-backfills/{backfill_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/agent-backfills/{backfill_id}/run")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["succeeded_count"] == 2
    assert client.post(f"/agent-backfills/{backfill_id}/run").status_code == 409
    assert client.post(f"/agent-backfills/{backfill_id}/rerun-failed").status_code == 409
    assert client.post(f"/agent-backfills/{backfill_id}/cancel").status_code == 409
    assert client.post(f"/agent-backfills/{backfill_id}/pause").status_code == 409

    queued_for_cancel = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001"], "client_id": "acme"},
    )
    cancelled = client.post(f"/agent-backfills/{queued_for_cancel.json()['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    disabled = client.post(
        "/agents",
        json={
            "name": "Disabled backfill target",
            "enabled": False,
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    failed_backfill = client.post(
        "/agent-backfills",
        json={
            "agent_id": disabled.json()["id"],
            "entity_ids": ["TCK-1001"],
            "client_id": "acme",
        },
    )
    failed_run = client.post(f"/agent-backfills/{failed_backfill.json()['id']}/run")
    assert failed_run.status_code == 200
    assert failed_run.json()["status"] == "completed_with_errors"
    assert failed_run.json()["failed_entity_ids"] == ["TCK-1001"]
    rerun = client.post(f"/agent-backfills/{failed_backfill.json()['id']}/rerun-failed")
    assert rerun.status_code == 200
    assert rerun.json()["failed_count"] == 1
    assert client.post(f"/agent-backfills/{failed_backfill.json()['id']}/rerun-failed").status_code == 200

    duplicate = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001", "TCK-1001"], "client_id": "acme"},
    )
    missing_ticket = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["NOPE"], "client_id": "acme"},
    )
    unknown_agent = client.post(
        "/agent-backfills",
        json={"agent_id": "no-such-agent", "entity_ids": ["TCK-1001"], "client_id": "acme"},
    )
    assert duplicate.status_code == 422
    assert missing_ticket.status_code == 404
    assert unknown_agent.status_code == 404
    assert client.get("/agent-backfills/99999").status_code == 404
    assert client.post("/agent-backfills/99999/run").status_code == 404
    assert client.post("/agent-backfills/99999/pause").status_code == 404
    assert client.post("/agent-backfills/99999/cancel").status_code == 404
    assert client.post("/agent-backfills/99999/rerun-failed").status_code == 404

    from wait_local_agent.agents import AgentExecutionResult

    def synthetic_failure(self, definition, *, entity_id, actor, input_payload):
        return AgentExecutionResult(
            run_id=0,
            agent_id=definition.id,
            status="failed",
            current_step=0,
            steps=[],
        )

    monkeypatch.setattr(app_module.AgentService, "run", synthetic_failure)
    synthetic_backfill = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001"], "client_id": "acme"},
    )
    synthetic_run = client.post(f"/agent-backfills/{synthetic_backfill.json()['id']}/run")
    assert synthetic_run.status_code == 200
    assert synthetic_run.json()["failed_count"] == 1
    assert synthetic_run.json()["run_ids"] == []

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    secure_client = TestClient(create_app(secure))
    assert secure_client.get("/agent-backfills", headers=_auth("viewer-token")).status_code == 403
    assert secure_client.get(
        "/agent-backfills/1", headers=_auth("viewer-token")
    ).status_code == 403
    assert secure_client.post(
        "/agent-backfills",
        headers=_auth("tech-token"),
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001"]},
    ).status_code == 403


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
    assert approved.json()["execution_status"] == "succeeded"
    assert approved.json()["execution_result_json"]
    assert executed[0].ticket_id == "HALO-42"
    assert any(event["event_type"] == "halopsa.write" for event in events.json())


def test_event_history_filters_by_client_id(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "viewer_token": "viewer-token",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
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
    store.create_approval_request("TCK-ACME", "ticket.assign", {"ticket_id": "TCK-ACME"}, client_id="acme")
    store.create_approval_request("TCK-BETA", "ticket.assign", {"ticket_id": "TCK-BETA"}, client_id="beta")
    client = TestClient(create_app(secure_settings))

    filtered = client.get("/event-history", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    blank = client.get("/event-history", params={"client_id": ""}, headers=_auth("viewer-token"))
    all_events = client.get("/event-history", headers=_auth("viewer-token"))

    assert filtered.status_code == 200
    assert filtered.json()
    assert all(event["client_id"] == "acme" for event in filtered.json())
    assert len(blank.json()) == len(all_events.json())


def test_smart_action_runs_and_ticket_lookup_are_client_scoped(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.executemany(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("TCK-ACME", "Acme", "MFA reset", "Sign-in blocked", "High", "Open", "acme"),
                ("TCK-BETA", "Beta", "MFA reset", "Sign-in blocked", "High", "Open", "beta"),
            ],
        )
    client = TestClient(create_app(settings))

    acme = client.post(
        "/smart-actions/ticket-triage/invoke",
        json={"payload": {"ticket_id": "TCK-ACME"}, "client_id": "acme"},
    )
    beta = client.post(
        "/smart-actions/ticket-triage/invoke",
        json={"payload": {"ticket_id": "TCK-BETA"}, "client_id": "beta"},
    )
    listed = client.get("/smart-actions/runs", params={"client_id": "acme"})
    hidden = client.get(
        f"/smart-actions/runs/{beta.json()['run_id']}", params={"client_id": "acme"}
    )
    cross_tenant = client.post(
        "/smart-actions/ticket-triage/invoke",
        json={"payload": {"ticket_id": "TCK-BETA"}, "client_id": "acme"},
    )

    assert acme.status_code == 200
    assert beta.status_code == 200
    assert listed.status_code == 200
    assert [run["client_id"] for run in listed.json()] == ["acme"]
    assert hidden.status_code == 404
    assert cross_tenant.json()["status"] == "failed"


def test_smart_action_scope_comes_from_authenticated_tenant(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "client_id": "acme",
        }
    )
    store = Store(secure_settings.data_path)
    acme = store.create_smart_action_run(
        "ticket-triage", "acme-actor", "success", "digest-a", {"tenant": "acme"}, [], client_id="acme"
    )
    store.create_smart_action_run(
        "ticket-triage", "beta-actor", "success", "digest-b", {"tenant": "beta"}, [], client_id="beta"
    )
    client = TestClient(create_app(secure_settings))

    omitted = client.get("/smart-actions/runs", headers=_auth("viewer-token"))
    arbitrary = client.get(
        "/smart-actions/runs",
        params={"client_id": "beta"},
        headers=_auth("viewer-token"),
    )
    hidden = client.get(
        f"/smart-actions/runs/{acme.id}",
        params={"client_id": "beta"},
        headers=_auth("viewer-token"),
    )

    assert omitted.status_code == 200
    assert [run["client_id"] for run in omitted.json()] == ["acme"]
    assert [run["client_id"] for run in arbitrary.json()] == ["acme"]
    assert hidden.status_code == 200


def test_legacy_approval_rows_are_redacted_in_api_views(settings) -> None:
    store = Store(settings.data_path)
    approval = store.create_approval_request("TCK-LEGACY", "halopsa.add_note", {})
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            update approval_requests
            set payload_json = ?, comment = ?, execution_result_json = ?
            where id = ?
            """,
            (
                '{"fields":{"api_key":"legacy-secret"}}',
                "token=legacy-comment-secret",
                '{"output":{"password":"legacy-output-secret"}}',
                approval.id,
            ),
        )
    client = TestClient(create_app(settings))

    response = client.get(f"/approval-requests/{approval.id}")
    payload = response.json()

    assert response.status_code == 200
    assert "legacy-secret" not in response.text
    assert "legacy-comment-secret" not in response.text
    assert "legacy-output-secret" not in response.text
    assert payload["payload"]["fields"]["api_key"] == "[redacted]"
    assert payload["output"]["output"]["password"] == "[redacted]"


def test_halopsa_manual_execute_rejects_non_approved_and_non_halopsa(settings) -> None:
    store = Store(settings.data_path)
    halo = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-1", "action_type": "add_note", "fields": {}},
    )
    other = store.create_approval_request("TCK-1", "ticket.draft_response", {"ticket_id": "TCK-1"})
    client = TestClient(create_app(settings))

    pending = client.post(f"/connectors/halopsa/approval-requests/{halo.id}/execute")
    store.update_approval_request(other.id or 0, "approved")
    non_halo = client.post(f"/connectors/halopsa/approval-requests/{other.id}/execute")
    missing = client.post("/connectors/halopsa/approval-requests/999/execute")

    assert pending.status_code == 409
    assert non_halo.status_code == 400
    assert missing.status_code == 404


def test_halopsa_manual_execute_records_blocked_and_rejects_repeat_success(
    settings, monkeypatch
) -> None:
    class FakeHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def execute_write(self, request):
            return HaloWriteResult("succeeded", "posted", request.action_type, request.ticket_id)

    store = Store(settings.data_path)
    blocked = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-1", "action_type": "add_note", "fields": {}},
    )
    store.update_approval_request(blocked.id or 0, "approved")
    client = TestClient(create_app(settings))

    blocked_response = client.post(f"/connectors/halopsa/approval-requests/{blocked.id}/execute")

    assert blocked_response.status_code == 200
    assert blocked_response.json()["execution_status"] == "blocked"

    monkeypatch.setattr(app_module, "HaloPSAClient", FakeHaloClient)
    success_store = Store(settings.data_path)
    approval = success_store.create_approval_request(
        "HALO-2",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-2", "action_type": "add_note", "fields": {}},
    )
    success_store.update_approval_request(approval.id or 0, "approved")
    success_client = TestClient(app_module.create_app(settings))
    first = success_client.post(f"/connectors/halopsa/approval-requests/{approval.id}/execute")
    second = success_client.post(f"/connectors/halopsa/approval-requests/{approval.id}/execute")

    assert first.json()["execution_status"] == "succeeded"
    assert second.status_code == 400


def test_halopsa_write_health_api(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/connectors/halopsa/write-health")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"


def test_hudu_api_surfaces_blocked_and_mocked_reads(settings, monkeypatch) -> None:
    class FakeHuduClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return HaloReadResult("ready", "ok", 0)

        def list_companies(self, page: int = 1, page_size: int | None = None):
            return _hudu_response([HuduCompany("C-1", "Contoso", False)])

        def list_articles(
            self,
            company_id: str | None = None,
            page: int = 1,
            page_size: int | None = None,
        ):
            return _hudu_response([HuduArticle("A-1", "Runbook", "C-1", "F-1", "", "")])

        def get_article(self, article_id: str):
            return _hudu_response([HuduArticle(article_id, "Runbook", "C-1", "F-1", "", "")])

        def list_folders(
            self,
            company_id: str | None = None,
            page: int = 1,
            page_size: int | None = None,
        ):
            return _hudu_response([HuduFolder("F-1", "Ops", "C-1", "")])

    blocked = TestClient(create_app(settings)).get("/connectors/hudu/health")
    monkeypatch.setattr(app_module, "HuduClient", FakeHuduClient)
    client = TestClient(app_module.create_app(settings))

    health = client.get("/connectors/hudu/health")
    companies = client.get("/connectors/hudu/companies")
    articles = client.get("/connectors/hudu/articles")
    article = client.get("/connectors/hudu/articles/A-1")
    folders = client.get("/connectors/hudu/folders")
    audit = client.get("/audit")

    assert blocked.json()["status"] == "blocked"
    assert health.json()["status"] == "ready"
    assert companies.json()["items"][0]["name"] == "Contoso"
    assert articles.json()["items"][0]["name"] == "Runbook"
    assert article.json()["items"][0]["id"] == "A-1"
    assert folders.json()["items"][0]["name"] == "Ops"
    assert any(event["event_type"] == "hudu.read" for event in audit.json())


def test_connectwise_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeConnectWiseClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ConnectWise ready", 0)

        def list_tickets(self, *, page=1, page_size=25, conditions=None):
            return ConnectWiseReadResponse(
                ConnectorReadResult(
                    "ready", f"tickets page={page} size={page_size} {conditions or ''}", 1
                ),
                [{"id": "42", "summary": "Printer offline"}],
            )

        def get_ticket(self, ticket_id):
            return ConnectWiseReadResponse(
                ConnectorReadResult("ready", "ticket ready", 1),
                [{"id": ticket_id, "summary": "Printer offline"}],
            )

        def list_companies(self, *, page=1, page_size=25, conditions=None):
            return ConnectWiseReadResponse(
                ConnectorReadResult("ready", "company ready", 1),
                [{"id": "C-1", "name": "Contoso", "status": "Active"}],
            )

    monkeypatch.setattr(app_module, "ConnectWiseClient", FakeConnectWiseClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/connectwise/health")
    tickets = client.get(
        "/connectors/connectwise/tickets",
        params={"page": 2, "page_size": 10, "conditions": "status/name = 'Open'"},
    )
    ticket = client.get("/connectors/connectwise/tickets/42")
    companies = client.get("/connectors/connectwise/companies")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert tickets.json()["items"][0]["id"] == "42"
    assert ticket.json()["items"][0]["id"] == "42"
    assert companies.json()["items"][0]["name"] == "Contoso"
    assert any(connector["id"] == "connectwise" for connector in connectors.json())
    assert any(event["event_type"] == "connectwise.read" for event in audit.json())


def test_connectwise_routes_keep_viewer_auth_boundary(settings) -> None:
    secure_settings = settings.__class__(
        **{**settings.__dict__, "demo_mode": False, "api_token": "api-secret"}
    )
    client = TestClient(create_app(secure_settings))

    response = client.get("/connectors/connectwise/health")

    assert response.status_code == 401


def test_syncro_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeSyncroClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "Syncro ready", 0)

        def list_tickets(self, **kwargs):
            return SyncroReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"id": "42", "subject": "Printer offline"}],
            )

        def get_ticket(self, ticket_id):
            return SyncroReadResponse(
                ConnectorReadResult("ready", "ticket ready", 1),
                [{"id": ticket_id, "subject": "Printer offline"}],
            )

        def list_customers(self, **kwargs):
            return SyncroReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"id": "7", "name": "Contoso"}],
            )

        def get_customer(self, customer_id):
            return SyncroReadResponse(
                ConnectorReadResult("ready", "customer ready", 1),
                [{"id": customer_id, "name": "Contoso"}],
            )

    monkeypatch.setattr(app_module, "SyncroClient", FakeSyncroClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/syncro/health")
    tickets = client.get(
        "/connectors/syncro/tickets",
        params={"page": 2, "query": "printer", "customer_id": "7", "status": "Open"},
    )
    ticket = client.get("/connectors/syncro/tickets/42")
    customers = client.get("/connectors/syncro/customers", params={"query": "Contoso"})
    customer = client.get("/connectors/syncro/customers/7")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert tickets.json()["items"][0]["id"] == "42"
    assert ticket.json()["items"][0]["id"] == "42"
    assert customers.json()["items"][0]["name"] == "Contoso"
    assert customer.json()["items"][0]["id"] == "7"
    assert any(connector["id"] == "syncro" for connector in connectors.json())
    assert any(event["event_type"] == "syncro.read" for event in audit.json())


def test_servicenow_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeServiceNowClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ServiceNow ready", 0)

        def list_incidents(self, **kwargs):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"sys_id": "abc123", "number": "INC001"}],
            )

        def get_incident(self, sys_id):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", "incident ready", 1),
                [{"sys_id": sys_id, "number": "INC001"}],
            )

        def list_companies(self, **kwargs):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"sys_id": "co-1", "name": "Contoso"}],
            )

        def get_company(self, sys_id):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", "company ready", 1),
                [{"sys_id": sys_id, "name": "Contoso"}],
            )

    monkeypatch.setattr(app_module, "ServiceNowClient", FakeServiceNowClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/servicenow/health")
    incidents = client.get(
        "/connectors/servicenow/incidents",
        params={"page": 2, "page_size": 10, "query": "active=true"},
    )
    incident = client.get("/connectors/servicenow/incidents/abc123")
    companies = client.get("/connectors/servicenow/companies")
    company = client.get("/connectors/servicenow/companies/co-1")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert incidents.json()["items"][0]["number"] == "INC001"
    assert incident.json()["items"][0]["sys_id"] == "abc123"
    assert companies.json()["items"][0]["name"] == "Contoso"
    assert company.json()["items"][0]["sys_id"] == "co-1"
    assert any(connector["id"] == "servicenow" for connector in connectors.json())
    assert any(event["event_type"] == "servicenow.read" for event in audit.json())


def test_servicenow_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, viewer_token="viewer-secret")
    response = TestClient(create_app(settings)).get("/connectors/servicenow/health")
    assert response.status_code == 401


def test_knowledge_api_missing_path_returns_400(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": "examples/sample_docs/missing.md"})

    assert response.status_code == 400


def _seed_execution_tickets(store: Store) -> None:
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))


def test_executions_api_lists_and_details_runs(settings) -> None:
    store = Store(settings.data_path)
    _seed_execution_tickets(store)
    client = TestClient(create_app(settings))

    run = client.post(
        "/workflows/templates/ticket-triage/runs", json={"ticket_id": "TCK-1001"}
    )
    assert run.status_code == 200

    listed = client.get("/executions")
    assert listed.status_code == 200
    executions = listed.json()
    assert len(executions) == 1
    assert executions[0]["run_kind"] == "workflow"
    assert executions[0]["status"] == "completed"
    execution_id = executions[0]["id"]

    filtered = client.get("/executions", params={"kind": "smart_action"})
    assert filtered.status_code == 200
    assert filtered.json() == []
    by_status = client.get("/executions", params={"status": "completed"})
    assert len(by_status.json()) == 1
    ranged = client.get("/executions", params={"from": "2000-01-01", "to": "2000-01-02"})
    assert ranged.json() == []

    detail = client.get(f"/executions/{execution_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == execution_id
    assert [step["ordinal"] for step in payload["steps"]] == [0]
    assert payload["steps"][0]["kind"] == "workflow.template"
    assert payload["steps"][0]["input"]["ticket_id"] == "TCK-1001"
    assert payload["artifacts"] == []

    missing = client.get("/executions/9999")
    assert missing.status_code == 404


def test_executions_api_serves_smart_action_artifact(settings) -> None:
    store = Store(settings.data_path)
    _seed_execution_tickets(store)
    client = TestClient(create_app(settings))

    invoke = client.post(
        "/smart-actions/ticket-triage/invoke", json={"payload": {"ticket_id": "TCK-1001"}}
    )
    assert invoke.status_code == 200

    detail = client.get("/executions", params={"kind": "smart_action"}).json()[0]
    execution = client.get(f"/executions/{detail['id']}").json()
    assert execution["artifacts"]
    artifact = execution["artifacts"][0]
    assert "storage_path" not in artifact

    download = client.get(f"/executions/{detail['id']}/artifacts/{artifact['id']}")
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == artifact["sha256"]

    wrong_run = client.get(f"/executions/{detail['id'] + 1}/artifacts/{artifact['id']}")
    assert wrong_run.status_code == 404
    missing_artifact = client.get(f"/executions/{detail['id']}/artifacts/9999")
    assert missing_artifact.status_code == 404


def test_executions_api_enforces_tenant_scope(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    _seed_execution_tickets(store)
    acme_run = store.create_execution_run(
        "workflow", 1, "a", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test", client_id="acme",
    )
    beta_run = store.create_execution_run(
        "workflow", 2, "b", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test", client_id="beta",
    )
    assert acme_run.id is not None and beta_run.id is not None
    store.add_execution_step(
        acme_run.id, 0, "workflow.template", "t", "completed",
        "2026-08-01T09:00:00+00:00", "2026-08-01T09:01:00+00:00",
        "d", "d", "{}", "{}", "",
    )
    store.add_execution_artifact(
        acme_run.id, 0, "a.bin", "application/octet-stream", 1, "f" * 64, "/tmp/nope"
    )
    client = TestClient(create_app(secure_settings))

    viewer_list = client.get("/executions", headers=_auth("viewer-token"))
    assert viewer_list.status_code == 200
    assert [run["id"] for run in viewer_list.json()] == [acme_run.id]

    foreign_detail = client.get(f"/executions/{beta_run.id}", headers=_auth("viewer-token"))
    assert foreign_detail.status_code == 404
    foreign_artifact = client.get(
        f"/executions/{beta_run.id}/artifacts/1", headers=_auth("tech-token")
    )
    assert foreign_artifact.status_code == 404

    admin_list = client.get("/executions", headers=_auth("admin-token"))
    assert {run["id"] for run in admin_list.json()} == {acme_run.id, beta_run.id}
    admin_filtered = client.get(
        "/executions", params={"client_id": "beta"}, headers=_auth("admin-token")
    )
    assert [run["id"] for run in admin_filtered.json()] == [beta_run.id]
    admin_detail = client.get(f"/executions/{beta_run.id}", headers=_auth("admin-token"))
    assert admin_detail.status_code == 200

    # The artifact file name must equal its content digest; a tampered path 404s.
    artifacts = store.list_execution_artifacts(acme_run.id)
    tampered = client.get(
        f"/executions/{acme_run.id}/artifacts/{artifacts[0].id}", headers=_auth("tech-token")
    )
    assert tampered.status_code == 404


def test_executions_api_hides_all_runs_from_tenantless_principal(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    store.create_execution_run(
        "workflow", 1, "a", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test", client_id="acme",
    )
    client = TestClient(create_app(secure_settings))

    listed = client.get("/executions", headers=_auth("viewer-token"))
    detail = client.get("/executions/1", headers=_auth("viewer-token"))
    analytics = client.get("/analytics/summary", headers=_auth("viewer-token"))

    assert listed.json() == []
    assert detail.status_code == 404
    assert analytics.json()["success_rate"]["total"] == 0
    assert analytics.json()["estimated_minutes_saved"]["estimate"] is True


def test_analytics_summary_api_returns_metric_groups(settings) -> None:
    store = Store(settings.data_path)
    _seed_execution_tickets(store)
    client = TestClient(create_app(settings))

    invoke = client.post(
        "/smart-actions/ticket-triage/invoke", json={"payload": {"ticket_id": "TCK-1001"}}
    )
    assert invoke.status_code == 200
    failed = client.post(
        "/smart-actions/ticket-triage/invoke", json={"payload": {"ticket_id": "NOPE"}}
    )
    assert failed.status_code == 200

    response = client.get("/analytics/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["success_rate"]["total"] == 2
    assert summary["success_rate"]["succeeded"] == 1
    assert summary["failures_by_status"] == [{"status": "failed", "count": 1}]
    assert len(summary["executions_over_time"]) == 1
    assert summary["activity_breakdown"]
    time_saved = summary["estimated_minutes_saved"]
    assert time_saved["estimate"] is True
    assert time_saved["minutes"] == 4
    assert "estimate" in time_saved["derivation"]


def test_execution_steps_are_redacted_at_serialization(settings) -> None:
    store = Store(settings.data_path)
    run = store.create_execution_run(
        "smart_action", 1, "tech", "success", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test",
    )
    assert run.id is not None
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into execution_steps
              (execution_run_id, ordinal, kind, name, status, started_at, finished_at,
               input_digest, output_digest, input_json, output_json, error_detail)
            values (?, 0, 'smart_action.invoke', 'legacy', 'success', ?, ?, 'd', 'd', ?, '{}', '')
            """,
            (
                run.id,
                "2026-08-01T09:00:00+00:00",
                "2026-08-01T09:01:00+00:00",
                '{"note":"password=legacy-secret"}',
            ),
        )
    client = TestClient(create_app(settings))

    detail = client.get(f"/executions/{run.id}")

    assert detail.status_code == 200
    assert "legacy-secret" not in detail.text


def _read_response(items):
    return app_module.HaloReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def _hudu_response(items):
    return app_module.HuduReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
