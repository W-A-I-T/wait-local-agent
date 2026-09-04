from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.support import ensure_test_client, ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.api.schemas import ClientReportRequest
from wait_local_agent.collectors import default_registry
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import Store


def test_api_lists_exactly_fourteen_collector_modules(settings, isolated_default_registry) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/collectors/modules")

    assert response.status_code == 200
    modules = response.json()
    registered_ids = [module.manifest.id for module in default_registry.list()]
    assert [module["id"] for module in modules] == registered_ids
    assert len(modules) == len(registered_ids) == 14

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
