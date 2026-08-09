from __future__ import annotations

import json
from dataclasses import replace

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app
from wait_local_agent.reports.models import ReportType
from wait_local_agent.reports.msp import (
    build_automation_opportunity_report,
    build_qbr_report,
)
from wait_local_agent.reports.service import ReportService
from wait_local_agent.store import Store


def _seed_local_evidence(store: Store, tmp_path) -> None:
    ticket_file = tmp_path / "tickets.json"
    ticket_file.write_text(
        json.dumps(
            [
                {
                    "id": "QBR-1",
                    "client": "Acme",
                    "subject": "Printer offline",
                    "body": "A printer is offline.",
                    "priority": "high",
                    "status": "resolved",
                    "client_id": "acme",
                    "requester_id": "user-1",
                    "created_at": "2026-08-05T10:00:00+00:00",
                    "updated_at": "2026-08-06T10:00:00+00:00",
                },
                {
                    "id": "QBR-2",
                    "client": "Acme",
                    "subject": "New laptop",
                    "body": "A laptop is needed.",
                    "priority": "normal",
                    "status": "open",
                    "client_id": "acme",
                    "requester_id": "user-2",
                    "created_at": "2026-08-07T10:00:00+00:00",
                    "updated_at": "2026-08-07T10:00:00+00:00",
                },
            ]
        ),
        encoding="utf-8",
    )
    assert store.ingest_ticket_file(ticket_file) == 2
    action = store.create_smart_action_run(
        "ticket-triage",
        "technician",
        "success",
        "digest",
        {"status": "success"},
        [],
        client_id="acme",
    )
    assert action.client_id == "acme"
    store.create_execution_run(
        "smart_action",
        action.id,
        "technician",
        "completed",
        "2026-08-08T10:00:00+00:00",
        "2026-08-08T10:00:01+00:00",
        "manual",
        client_id="acme",
    )


def test_qbr_and_automation_reports_use_local_evidence_and_label_estimates(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    _seed_local_evidence(store, tmp_path)

    qbr_sections, qbr_metadata = build_qbr_report(
        store,
        {"ticket-triage": 4},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    opportunity_sections, opportunity_metadata = build_automation_opportunity_report(
        store,
        {"ticket-triage": 4},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-08-31",
    )

    assert qbr_sections[0].findings[0]["ticket_count"] == 2
    assert qbr_sections[2].findings[0]["estimated_minutes_saved"]["estimate"] is True
    assert qbr_metadata["evidence_status"] in {"partial", "completed"}
    assert opportunity_sections[0].findings[0]["action_id"] == "ticket-triage"
    assert opportunity_metadata["estimated_minutes_saved"]["estimate"] is True


def test_report_generation_api_is_client_scoped_and_audited(settings, tmp_path) -> None:
    store = Store(settings.data_path)
    _seed_local_evidence(store, tmp_path)
    client = TestClient(create_app(settings))

    qbr = client.post(
        "/reports/qbr",
        json={"client_id": "acme", "period_start": "2026-08-01", "period_end": "2026-08-31"},
    )
    opportunity = client.post(
        "/reports/automation-opportunity",
        json={"client_id": "acme", "period_start": "2026-08-01", "period_end": "2026-08-31"},
    )

    assert qbr.status_code == 200
    assert qbr.json()["report_type"] == ReportType.QBR.value
    assert qbr.json()["client_id"] == "acme"
    assert opportunity.status_code == 200
    assert opportunity.json()["report_type"] == ReportType.AUTOMATION_OPPORTUNITY.value
    assert any(
        event.event_type == "report.created" and event.client_id == "acme"
        for event in store.list_audit_events()
    )


def test_report_reads_fail_closed_for_bound_viewer(settings) -> None:
    service = ReportService(Store(settings.data_path))
    acme = service.create_report(ReportType.QBR, "Acme", [], client_id="acme")
    globex = service.create_report(ReportType.QBR, "Globex", [], client_id="globex")
    secured = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        viewer_token="viewer-token",
        client_id="acme",
    )
    client = TestClient(create_app(secured))
    viewer = {"Authorization": "Bearer viewer-token"}
    admin = {"Authorization": "Bearer admin-token"}

    listing = client.get("/reports", headers=viewer)
    forbidden_detail = client.get(f"/reports/{globex.id}", headers=viewer)
    forbidden_export = client.get(f"/reports/{globex.id}/export", headers=viewer)
    admin_listing = client.get("/reports", headers=admin)

    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [acme.id]
    assert forbidden_detail.status_code == 404
    assert forbidden_export.status_code == 404
    assert {row["id"] for row in admin_listing.json()} == {acme.id, globex.id}


def test_report_generation_rejects_invalid_period_and_unbound_viewer(settings) -> None:
    invalid = TestClient(create_app(settings)).post(
        "/reports/qbr",
        json={"client_id": "acme", "period_start": "2026-08-31", "period_end": "2026-08-01"},
    )
    assert invalid.status_code == 400

    secured = replace(settings, demo_mode=False, viewer_token="viewer-token", client_id="")
    unbound = TestClient(create_app(secured)).post(
        "/reports/qbr",
        headers={"Authorization": "Bearer viewer-token"},
        json={"period_start": "2026-08-01", "period_end": "2026-08-31"},
    )
    assert unbound.status_code == 403


def test_cli_generates_client_reports(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_DEMO_MODE", "true")
    monkeypatch.setenv("WAIT_CLIENT_ID", "acme")
    runner = CliRunner()

    qbr = runner.invoke(
        app,
        [
            "reports",
            "qbr",
            "--period-start",
            "2026-08-01",
            "--period-end",
            "2026-08-31",
            "--client-id",
            "acme",
        ],
    )
    opportunity = runner.invoke(
        app,
        [
            "reports",
            "automation-opportunity",
            "--period-start",
            "2026-08-01",
            "--period-end",
            "2026-08-31",
            "--client-id",
            "acme",
        ],
    )

    assert qbr.exit_code == 0, qbr.stdout
    assert '"report_type": "qbr"' in qbr.stdout
    assert opportunity.exit_code == 0, opportunity.stdout
    assert '"report_type": "automation_opportunity"' in opportunity.stdout
