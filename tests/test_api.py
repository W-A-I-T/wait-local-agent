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


def test_missing_ticket_returns_404(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/tickets/DOES-NOT-EXIST/summary")

    assert response.status_code == 404

