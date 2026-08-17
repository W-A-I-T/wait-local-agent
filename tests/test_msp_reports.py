from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from tests.support import ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app
from wait_local_agent.reports.models import ReportType
from wait_local_agent.reports.msp import (
    _in_period,
    _period,
    _qbr_evidence_status,
    build_automation_opportunity_report,
    build_qbr_report,
)
from wait_local_agent.reports.service import ReportService
from wait_local_agent.store import Store


def _insert_smart_action_runs(
    store: Store,
    runs: list[tuple[str, str, str, int | None]],
    *,
    client_id: str = "acme",
) -> None:
    with store._connect() as connection:  # noqa: SLF001
        for action_id, status, created_at, approval_id in runs:
            connection.execute(
                """
                insert into smart_action_runs
                  (action_id, actor, status, payload_digest, output_json,
                   evidence_json, approval_id, created_at, updated_at, client_id, error_detail)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    "technician",
                    status,
                    "digest",
                    "{}",
                    "[]",
                    approval_id,
                    created_at,
                    created_at,
                    client_id,
                    "",
                ),
            )


def _action_run_rows(
    action_id: str,
    statuses: list[str],
    *,
    date_prefix: str = "2026-08",
    approval_indexes: set[int] | None = None,
) -> list[tuple[str, str, str, int | None]]:
    approved = approval_indexes or set()
    return [
        (
            action_id,
            status,
            f"{date_prefix}-{index + 1:02d}T10:00:00+00:00",
            index + 100 if index in approved else None,
        )
        for index, status in enumerate(statuses)
    ]


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
    assert ingest_local(store, ticket_file) == 2
    _insert_smart_action_runs(
        store,
        _action_run_rows(
            "ticket-triage",
            ["success", "completed", "success", "success", "failed"],
            approval_indexes={0, 2},
        ),
    )
    action = store.list_smart_action_runs(client_id="acme")[0]
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
    candidate = opportunity_sections[0].findings[0]
    assert candidate["action_id"] == "ticket-triage"
    assert candidate["attempts"] == 5
    assert candidate["successes"] == 4
    assert candidate["failures"] == 1
    assert candidate["success_rate"] == pytest.approx(0.8)
    assert candidate["approval_burden"] == 2
    assert candidate["estimated_minutes_saved"] == 16
    assert candidate["estimate"] is True
    assert "repeated" not in candidate["candidate_reason"].lower()
    assert qbr_sections[2].findings[0]["top_candidates"][0]["successful_runs"] == 4
    assert "repeated" not in qbr_sections[2].recommendations[0].lower()
    assert opportunity_metadata["estimated_minutes_saved"]["estimate"] is True


def test_automation_opportunity_excludes_below_threshold_actions(settings) -> None:
    store = Store(settings.data_path)
    _insert_smart_action_runs(
        store,
        _action_run_rows("one-success", ["success"])
        + _action_run_rows("four-attempts", ["success"] * 4)
        + _action_run_rows("low-rate", ["success", "success", "success", "failed", "failed"])
        + _action_run_rows("qualifying", ["success", "completed", "success", "success", "failed"])
        + _action_run_rows("zero-savings", ["success", "success", "success", "success", "failed"]),
    )

    sections, metadata = build_automation_opportunity_report(
        store,
        {"qualifying": 5, "zero-savings": 0},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-08-31",
    )

    assert [finding["action_id"] for finding in sections[0].findings] == ["qualifying"]
    assert metadata["evidence_status"] == "completed"


def test_automation_opportunity_window_is_fail_closed(settings) -> None:
    store = Store(settings.data_path)
    _insert_smart_action_runs(
        store,
        _action_run_rows(
            "windowed",
            ["success", "completed", "success", "success", "failed"],
            date_prefix="2026-07",
        ),
    )

    short_sections, short_metadata = build_automation_opportunity_report(
        store,
        {"windowed": 4},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-08-30",
    )
    long_sections, long_metadata = build_automation_opportunity_report(
        store,
        {"windowed": 4},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-11-01",
    )
    valid_sections, valid_metadata = build_automation_opportunity_report(
        store,
        {"windowed": 4},
        client_id="acme",
        period_start="2026-07-01",
        period_end="2026-08-30",
    )

    assert short_sections[0].findings == []
    assert short_metadata["evidence_status"] == "window_out_of_range"
    assert short_metadata["window_days"] == 29
    assert long_sections[0].findings == []
    assert long_metadata["evidence_status"] == "window_out_of_range"
    assert long_metadata["window_days"] == 92
    assert [finding["action_id"] for finding in valid_sections[0].findings] == ["windowed"]
    assert valid_metadata["evidence_status"] == "completed"


def test_automation_opportunity_counts_approval_burden(settings) -> None:
    store = Store(settings.data_path)
    _insert_smart_action_runs(
        store,
        _action_run_rows(
            "approval-heavy",
            ["success", "completed", "success", "success", "failed"],
            approval_indexes={0, 1, 4},
        ),
    )

    sections, _ = build_automation_opportunity_report(
        store,
        {"approval-heavy": 3},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-08-31",
    )

    assert sections[0].findings[0]["approval_burden"] == 3


def test_msp_reports_fail_closed_for_empty_and_malformed_period_evidence(settings) -> None:
    store = Store(settings.data_path)
    store.create_smart_action_run(
        "ticket-triage",
        "technician",
        "failed",
        "digest",
        {"status": "failed"},
        [],
        client_id="acme",
    )

    _, qbr_metadata = build_qbr_report(
        store,
        {"ticket-triage": 4},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    _, opportunity_metadata = build_automation_opportunity_report(
        store,
        {"ticket-triage": 4},
        client_id="acme",
        period_start="2026-08-01",
        period_end="2026-08-31",
    )

    assert qbr_metadata["evidence_status"] == "no_evidence"
    assert opportunity_metadata["evidence_status"] == "no_evidence"
    assert not _in_period("", *_period("2026-08-01", "2026-08-31"))
    assert not _in_period("not-a-date", *_period("2026-08-01", "2026-08-31"))
    assert _qbr_evidence_status([], [object()], {"with_duration": 1}) == "completed"
    with pytest.raises(ValueError, match="ISO dates"):
        _period("not-a-date", "2026-08-31")
    with pytest.raises(ValueError, match="on or after"):
        _period("2026-08-31", "2026-08-01")


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

    secured = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        viewer_token="viewer-token",
        client_id="",
    )
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


def test_cli_schedules_bounded_client_report(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "scheduled-report.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(db_path))
    monkeypatch.setenv("WAIT_DEMO_MODE", "true")
    monkeypatch.setenv("WAIT_CLIENT_ID", "acme")
    result = CliRunner().invoke(
        app,
        [
            "reports",
            "schedule",
            "qbr",
            "--cron",
            "0 9 * * *",
            "--client-id",
            "acme",
            "--period-days",
            "30",
        ],
    )

    assert result.exit_code == 0, result.stdout
    job = Store(db_path).list_scheduled_jobs()[0]
    assert job.job_kind == "report"
    assert job.template_id == "qbr"
    assert json.loads(job.params_json)["client_id"] == "acme"
