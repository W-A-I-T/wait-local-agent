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
    approval = client.post("/tickets/TCK-1001/approvals", json={"status": "approved"})
    audit = client.get("/audit")

    assert summary.status_code == 200
    assert summary.json()["classification"] == "identity-access"
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"
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


def test_knowledge_api_missing_path_returns_400(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": "examples/sample_docs/missing.md"})

    assert response.status_code == 400
