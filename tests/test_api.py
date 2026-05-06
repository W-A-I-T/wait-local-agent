from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def test_health_reports_safe_defaults(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["write_actions_enabled"] is False
    assert response.json()["http_probing_enabled"] is False
    assert response.json()["cloud_fallback_enabled"] is False


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
    assert secrets.status_code == 200
    assert any(secret["key"] == "WAIT_HALOPSA_BASE_URL" for secret in secrets.json())
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


def test_workflow_and_halopsa_missing_resources_return_404(settings) -> None:
    client = TestClient(create_app(settings))

    missing_template = client.post(
        "/workflows/templates/nope/runs",
        json={"ticket_id": "TCK-1002"},
    )
    missing_ticket = client.post(
        "/connectors/halopsa/tickets/NOPE/drafts",
        json={"action_type": "add_note", "fields": {"note": "Draft"}},
    )
    missing_approval = client.post(
        "/approval-requests/999",
        json={"status": "approved"},
    )

    assert missing_template.status_code == 404
    assert missing_ticket.status_code == 404
    assert missing_approval.status_code == 404


def test_knowledge_api_missing_path_returns_400(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": "examples/sample_docs/missing.md"})

    assert response.status_code == 400
