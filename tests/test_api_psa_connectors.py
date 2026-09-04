from __future__ import annotations

from dataclasses import replace
from typing import Literal

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.autotask import AutotaskReadResponse
from wait_local_agent.connectwise import ConnectWiseReadResponse
from wait_local_agent.models import (
    ConnectorReadResult,
    HaloWriteRequest,
    HaloWriteResult,
)
from wait_local_agent.servicenow import ServiceNowReadResponse
from wait_local_agent.store import Store
from wait_local_agent.syncro import SyncroCommentsResponse, SyncroReadResponse


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

        def verify_write(
            self,
            request: HaloWriteRequest,
            write_result: HaloWriteResult,
            *,
            detail: dict[str, object] | None = None,
        ) -> Literal["verified", "unverified", "submitted"]:
            return "submitted"

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

    assert first.json()["execution_status"] == "submitted"
    assert second.status_code == 400

def test_halopsa_write_health_api(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/connectors/halopsa/write-health")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"

@pytest.mark.parametrize(
    "write_health_path",
    [
        "/connectors/halopsa/write-health",
        "/connectors/connectwise/write-health",
        "/connectors/servicenow/write-health",
        "/connectors/autotask/write-health",
    ],
)
def test_write_health_routes_use_connector_limit(
    settings, write_health_path: str
) -> None:
    rate_limited_settings = replace(settings, rate_limit_enabled=True)
    write_health_client = TestClient(create_app(rate_limited_settings))

    write_health_responses = [write_health_client.get(write_health_path) for _ in range(11)]

    assert all(response.status_code == 200 for response in write_health_responses[:10])
    assert write_health_responses[-1].status_code == 429

    provider_health_client = TestClient(create_app(rate_limited_settings))
    provider_health_responses = [provider_health_client.get("/connectors/halopsa/health") for _ in range(11)]

    assert all(response.status_code == 200 for response in provider_health_responses[:10])
    assert provider_health_responses[-1].status_code == 429

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

def test_connectwise_draft_rejects_unsupported_fields(settings) -> None:
    client = TestClient(create_app(settings))

    response = client.post(
        "/connectors/connectwise/tickets/42/drafts",
        json={"action_type": "update_status", "fields": {"status": "Closed"}},
    )

    assert response.status_code == 400
    assert "unsupported keys" in response.json()["detail"]

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

        def list_ticket_comments(self, ticket_id, **kwargs):
            return SyncroCommentsResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"id": "comment-1", "ticket_id": ticket_id, "body": "Reviewed"}],
                {"page": kwargs["page"], "per_page": kwargs["per_page"], "total_pages": 1},
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
    comments = client.get(
        "/connectors/syncro/tickets/42/comments", params={"page": 2, "per_page": 5}
    )
    customers = client.get("/connectors/syncro/customers", params={"query": "Contoso"})
    customer = client.get("/connectors/syncro/customers/7")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert tickets.json()["items"][0]["id"] == "42"
    assert ticket.json()["items"][0]["id"] == "42"
    assert comments.json()["items"][0]["body"] == "Reviewed"
    assert comments.json()["meta"] == {"page": 2, "per_page": 5, "total_pages": 1}
    assert customers.json()["items"][0]["name"] == "Contoso"
    assert customer.json()["items"][0]["id"] == "7"
    assert any(connector["id"] == "syncro" for connector in connectors.json())
    connector_tiers = {connector["id"]: connector["tier"] for connector in connectors.json()}
    assert connector_tiers["syncro"] == "instance"
    assert connector_tiers["itglue"] == "appliance-wide"
    assert all(connector["tier"] in {"instance", "appliance-wide"} for connector in connectors.json())
    assert any(event["event_type"] == "syncro.read" for event in audit.json())

def test_servicenow_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeServiceNowClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ServiceNow ready", 0)

        def write_health(self):
            return ConnectorReadResult("ready", "ServiceNow writes ready", 0)

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
    write_health = client.get("/connectors/servicenow/write-health")
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
    assert write_health.status_code == 200
    assert write_health.json()["status"] == "ready"
    assert incidents.json()["items"][0]["number"] == "INC001"
    assert incident.json()["items"][0]["sys_id"] == "abc123"
    assert companies.json()["items"][0]["name"] == "Contoso"
    assert company.json()["items"][0]["sys_id"] == "co-1"
    assert any(connector["id"] == "servicenow" for connector in connectors.json())
    assert any(event["event_type"] == "servicenow.read" for event in audit.json())

def test_servicenow_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, admin_token="admin-token", viewer_token="viewer-secret")
    response = TestClient(create_app(settings)).get("/connectors/servicenow/health")
    assert response.status_code == 401

def test_autotask_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeAutotaskClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "Autotask ready", 0)

        def write_health(self):
            return ConnectorReadResult("ready", "Autotask writes ready", 0)

        def list_tickets(self, **kwargs):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"id": "7", "ticket_number": "T-7"}],
            )

        def get_ticket(self, ticket_id):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", "ticket ready", 1),
                [{"id": ticket_id, "ticket_number": "T-7"}],
            )

        def list_companies(self, **kwargs):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"id": "3", "name": "Contoso"}],
            )

        def get_company(self, company_id):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", "company ready", 1),
                [{"id": company_id, "name": "Contoso"}],
            )

    monkeypatch.setattr(app_module, "AutotaskClient", FakeAutotaskClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/autotask/health")
    write_health = client.get("/connectors/autotask/write-health")
    tickets = client.get(
        "/connectors/autotask/tickets",
        params={"page": 2, "page_size": 10},
    )
    ticket = client.get("/connectors/autotask/tickets/7")
    companies = client.get("/connectors/autotask/companies")
    company = client.get("/connectors/autotask/companies/3")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert write_health.status_code == 200
    assert write_health.json()["message"] == "Autotask writes ready"
    assert tickets.json()["items"][0]["ticket_number"] == "T-7"
    assert ticket.json()["items"][0]["id"] == "7"
    assert companies.json()["items"][0]["name"] == "Contoso"
    assert company.json()["items"][0]["id"] == "3"
    assert any(connector["id"] == "autotask" for connector in connectors.json())
    assert any(event["event_type"] == "autotask.read" for event in audit.json())
    assert any(event["event_type"] == "autotask.write_health" for event in audit.json())

def test_autotask_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, admin_token="admin-token", viewer_token="viewer-secret")
    response = TestClient(create_app(settings)).get("/connectors/autotask/health")
    assert response.status_code == 401
