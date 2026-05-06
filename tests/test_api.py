from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.models import HaloReadResult, HaloTicket
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
    assert workflow_runs.json()[0]["status"] == "pending_approval"


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

    monkeypatch.setattr(app_module, "HaloPSAReadClient", FakeHaloClient)
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


def test_knowledge_api_missing_path_returns_400(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post("/knowledge/ingest", json={"path": "examples/sample_docs/missing.md"})

    assert response.status_code == 400


def _read_response(items):
    return app_module.HaloReadResponse(HaloReadResult("ready", "ok", len(items)), items)
