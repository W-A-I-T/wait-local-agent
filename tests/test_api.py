from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.models import (
    HaloReadResult,
    HaloTicket,
    HaloWriteResult,
    HuduArticle,
    HuduCompany,
    HuduFolder,
)
from wait_local_agent.store import Store


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
    filtered_audit = client.get("/audit", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    filtered_documents = client.get("/knowledge/documents", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    filtered_runs = client.get("/workflow-runs", params={"client_id": "acme"}, headers=_auth("viewer-token"))
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
    assert all(event["client_id"] == "acme" for event in filtered_audit.json())
    assert [document["title"] for document in filtered_documents.json()] == ["Acme"]
    assert [run["ticket_id"] for run in filtered_runs.json()] == ["TCK-ACME"]
    assert approved.status_code == 200
    assert approved.json()["approver_id"] == expected_approver_id
    assert any(
        event["event_type"] == "approval_request.updated" and event["approver_id"] == expected_approver_id
        for event in export.json()["events"]
    )
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
    delete = client.delete("/scheduled-jobs/999")

    assert missing_template.status_code == 404
    assert missing_ticket.status_code == 404
    assert missing_param.status_code == 422
    assert pause.status_code == 404
    assert resume.status_code == 404
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
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    Store(secure_settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))

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

        paused = client.post(f"/scheduled-jobs/{job_id}/pause", headers=_auth("tech-token"))
        resumed = client.post(f"/scheduled-jobs/{job_id}/resume", headers=_auth("tech-token"))
        deleted = client.delete(f"/scheduled-jobs/{job_id}", headers=_auth("tech-token"))

        assert paused.status_code == 200
        assert paused.json()["paused"] is True
        assert paused.json()["next_run_at"] is None
        assert resumed.status_code == 200
        assert resumed.json()["paused"] is False
        assert resumed.json()["next_run_at"] is not None
        assert deleted.status_code == 200
        assert deleted.json()["id"] == job_id
        assert len(app.state.scheduler._scheduler.get_jobs()) == 0
        assert client.get("/scheduled-jobs", headers=_auth("viewer-token")).json() == []


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


def test_knowledge_api_missing_path_returns_400(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": "examples/sample_docs/missing.md"})

    assert response.status_code == 400


def _read_response(items):
    return app_module.HaloReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def _hudu_response(items):
    return app_module.HuduReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
