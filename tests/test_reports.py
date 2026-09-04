from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from typer.testing import CliRunner

from tests.support import ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app
from wait_local_agent.reports.builders import (
    build_appliance_hardening_report,
    build_restore_evidence_report,
)
from wait_local_agent.reports.models import (
    GeneratedReport,
    ReportFormat,
    ReportSection,
    ReportType,
    sections_from_json,
)
from wait_local_agent.reports.msp import build_recurring_service_review_report
from wait_local_agent.reports.renderers import (
    REDACTED,
    redact_value,
    render_json,
    render_markdown,
    render_pdf,
    render_report,
)
from wait_local_agent.reports.schemas import REPORT_JSON_SCHEMA, validate_report_payload
from wait_local_agent.reports.service import ReportService, _metadata_evidence_status
from wait_local_agent.store import Store


def _sections() -> list[ReportSection]:
    return [
        ReportSection(
            title="Connector Coverage",
            summary="HaloPSA read paths verified against sandbox data.",
            findings=[{"connector": "halopsa", "status": "ready", "count": 4}],
            evidence=[{"path": "audit://event/12", "detail": "read health check"}],
            recommendations=["Enable Hudu credentials before the next run."],
        ),
        ReportSection(title="Empty Section", summary="No findings in this pass."),
    ]


def test_unknown_report_evidence_metadata_is_safe_by_default() -> None:
    assert _metadata_evidence_status({"evidence_status": "invented"}) == "not_run"


def _service(settings) -> ReportService:
    return ReportService(Store(settings.data_path))


def test_report_creation_persists_and_audits(settings) -> None:
    service = _service(settings)

    report = service.create_report(
        ReportType.CONNECTOR_HEALTH,
        "Connector Health Snapshot",
        _sections(),
        created_by="operator-1",
        client_id="client-9",
        project_id="project-3",
        metadata={"source": "unit-test"},
    )
    stored = service.get_report(report.id)
    events = service.store.list_audit_events()

    assert stored is not None
    assert stored == report
    assert stored.report_type is ReportType.CONNECTOR_HEALTH
    assert stored.metadata == {"source": "unit-test"}
    assert any(event.event_type == "report.created" for event in events)


def test_save_report_upserts_on_conflict(settings) -> None:
    service = _service(settings)
    report = service.create_report(ReportType.AUDIT_EXPORT, "First Title", _sections())

    service.store.save_report(replace(report, title="Second Title"))
    stored = service.get_report(report.id)

    assert stored is not None
    assert stored.title == "Second Title"
    assert len(service.list_reports()) == 1


def test_list_reports_filters_by_type_client_and_project(settings) -> None:
    service = _service(settings)
    service.create_report(ReportType.CONNECTOR_HEALTH, "A", _sections(), client_id="acme")
    service.create_report(
        ReportType.AUDIT_EXPORT, "B", _sections(), client_id="acme", project_id="p1"
    )
    service.create_report(ReportType.AUDIT_EXPORT, "C", _sections(), client_id="globex")

    by_type = service.list_reports(report_type=ReportType.AUDIT_EXPORT)
    by_client = service.list_reports(client_id="acme")
    by_both = service.list_reports(report_type=ReportType.AUDIT_EXPORT, client_id="acme")
    by_project = service.list_reports(project_id="p1")

    assert {report.title for report in by_type} == {"B", "C"}
    assert {report.title for report in by_client} == {"A", "B"}
    assert {report.title for report in by_both} == {"B"}
    assert {report.title for report in by_project} == {"B"}
    assert len(service.list_reports()) == 3


def test_json_render_round_trips_sections(settings) -> None:
    report = GeneratedReport.new(ReportType.QBR, "Quarterly Review", _sections())

    payload = json.loads(render_json(report))

    assert payload["id"] == report.id
    assert payload["report_type"] == "qbr"
    assert payload["sections"][0]["findings"][0]["connector"] == "halopsa"
    assert validate_report_payload(payload) == []
    assert sections_from_json(report.sections_json()) == report.sections


def test_hardening_and_restore_reports_are_not_run_without_evidence(settings) -> None:
    store = Store(settings.data_path)
    hardening_sections, hardening_metadata = build_appliance_hardening_report(store)
    restore_sections, restore_metadata = build_restore_evidence_report(store)

    hardening = _service(settings).create_report(
        ReportType.APPLIANCE_HARDENING,
        "Hardening",
        hardening_sections,
        metadata=hardening_metadata,
    )
    restore = _service(settings).create_report(
        ReportType.RESTORE_EVIDENCE,
        "Restore",
        restore_sections,
        metadata=restore_metadata,
    )

    with pytest.raises(KeyError):
        build_restore_evidence_report(store, run_id=999999)

    assert hardening.evidence_status == "not_run"
    assert restore.evidence_status == "not_run"
    assert json.loads(render_json(hardening))["evidence_status"] == "not_run"
    assert "Evidence status: `not_run`" in render_markdown(restore)


def test_restore_report_rechecks_a_missing_run_before_listing_evidence() -> None:
    class EventuallyAvailableStore:
        calls = 0

        def get_collector_run(self, run_id: int):
            self.calls += 1
            return None if self.calls == 1 else object()

        def get_restore_exercise(self, run_id: int):
            return None

        def list_restore_exercises(self, run_id=None):
            return []

    sections, metadata = build_restore_evidence_report(EventuallyAvailableStore(), run_id=1)  # type: ignore[arg-type]

    assert sections[0].summary == "0 restore exercises are attached to this run."
    assert metadata["evidence_status"] == "no_evidence"


def test_recurring_service_review_is_client_scoped_and_labels_missing_evidence(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute(
            "update tickets set client_id = ?, created_at = ?, updated_at = ? where id = ?",
            ("acme", "2026-01-01T00:00:00+00:00", "2026-01-05T00:00:00+00:00", "TCK-1001"),
        )
        connection.execute(
            "update tickets set client_id = ?, status = ?, created_at = ?, updated_at = ? where id = ?",
            ("acme", "closed", "2026-02-01T00:00:00+00:00", "2026-02-03T00:00:00+00:00", "TCK-1002"),
        )

    sections, metadata = build_recurring_service_review_report(
        store,
        client_id="acme",
        period_start="2026-01-01",
        period_end="2026-03-31",
        follow_up_after_days=14,
    )

    assert metadata["client_id"] == "acme"
    assert metadata["period_ticket_count"] == 2
    assert metadata["current_open_ticket_count"] == 1
    assert metadata["follow_up_candidate_count"] == 1
    assert metadata["evidence_status"] == "partial"
    assert "vendor_sla_compliance" in metadata["claims_excluded"]
    assert sections[1].findings[0]["candidates"][0]["ticket_id"] == "TCK-1001"
    assert store.list_tickets(client_id="other-client") == []

    with pytest.raises(ValueError, match="between 1 and 90"):
        build_recurring_service_review_report(
            store,
            client_id="acme",
            period_start="2026-01-01",
            period_end="2026-03-31",
            follow_up_after_days=0,
        )
    with pytest.raises(ValueError, match="between 1 and 90"):
        build_recurring_service_review_report(
            store,
            client_id="acme",
            period_start="2026-01-01",
            period_end="2026-03-31",
            follow_up_after_days=True,
        )

    with store._connect() as connection:
        connection.execute(
            "update tickets set created_at = ?, updated_at = ? where id = ?",
            ("", "", "TCK-1001"),
        )
    _, empty_timestamp_metadata = build_recurring_service_review_report(
        store,
        client_id="acme",
        period_start="2026-01-01",
        period_end="2026-03-31",
    )
    assert empty_timestamp_metadata["follow_up_candidate_count"] == 0

    with store._connect() as connection:
        connection.execute(
            "update tickets set created_at = ?, updated_at = ? where id = ?",
            ("not-a-date", "not-a-date", "TCK-1001"),
        )
    _, invalid_timestamp_metadata = build_recurring_service_review_report(
        store,
        client_id="acme",
        period_start="2026-01-01",
        period_end="2026-03-31",
    )
    assert invalid_timestamp_metadata["follow_up_candidate_count"] == 0


def test_markdown_render_contains_headers_and_recommendations() -> None:
    report = GeneratedReport.new(
        ReportType.CONNECTOR_HEALTH,
        "Connector Health Snapshot",
        _sections(),
        created_by="operator-1",
        client_id="client-9",
        project_id="project-3",
        metadata={"run": 7},
    )

    rendered = render_markdown(report)

    assert "# Connector Health Snapshot" in rendered
    assert "## Connector Coverage" in rendered
    assert "### Findings" in rendered
    assert "### Evidence" in rendered
    assert "### Recommendations" in rendered
    assert "Enable Hudu credentials before the next run." in rendered
    assert "operator-1" in rendered
    assert "client-9" in rendered
    assert "project-3" in rendered
    assert "## Metadata" in rendered


def test_render_report_dispatch_and_pdf_contains_report_content() -> None:
    report = GeneratedReport.new(ReportType.AUDIT_EXPORT, "Audit", _sections())

    json_export = render_report(report, ReportFormat.JSON)
    markdown_export = render_report(report, ReportFormat.MARKDOWN)
    assert isinstance(json_export, str) and json_export.startswith("{")
    assert isinstance(markdown_export, str) and markdown_export.startswith("# Audit")
    pdf = render_pdf(report)
    assert pdf.startswith(b"%PDF-")
    assert "Audit" in "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    dispatched_pdf = render_report(report, ReportFormat.PDF)
    assert isinstance(dispatched_pdf, bytes) and dispatched_pdf.startswith(b"%PDF-")
    with pytest.raises(ValueError, match="unsupported report format"):
        render_report(report, SimpleNamespace(value="xml"))  # type: ignore[arg-type]


def test_renders_never_include_secret_values() -> None:
    secret_value = "super-secret-material-9911"
    report = GeneratedReport.new(
        ReportType.CONNECTOR_HEALTH,
        "Secrets Check",
        [
            ReportSection(
                title="Credentials",
                summary="Connector credential probe.",
                findings=[{"api_key": secret_value, "client_secret": secret_value}],
                evidence=[{"nested": {"password": secret_value, "safe": "keep-me"}}],
            )
        ],
        metadata={"auth_token": secret_value, "authorization": f"Bearer {secret_value}"},
    )

    as_json = render_json(report)
    as_markdown = render_markdown(report)
    as_pdf = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(render_pdf(report))).pages)

    for rendered in (as_json, as_markdown, as_pdf):
        assert secret_value not in rendered
        assert REDACTED in rendered
    assert "keep-me" in as_json


def test_redact_value_covers_sensitive_and_deliberately_safe_values() -> None:
    payload = {
        "apiKey": "secret-value",
        "nested": [{"password": "nested-secret", "monkey": "keep-monkey"}],
        "keyboard": "keep-keyboard",
        "count": 3,
    }

    redacted = redact_value(payload)

    assert redacted == {
        "apiKey": REDACTED,
        "nested": [{"password": REDACTED, "monkey": "keep-monkey"}],
        "keyboard": "keep-keyboard",
        "count": 3,
    }


def test_sections_from_json_rejects_non_list_payload() -> None:
    try:
        sections_from_json('{"title": "not a list"}')
        raise AssertionError("non-list payloads must be rejected")
    except ValueError as exc:
        assert "list" in str(exc)


def test_schema_validation_reports_problems() -> None:
    assert "GeneratedReport" in str(REPORT_JSON_SCHEMA["title"])
    problems = validate_report_payload(
        {
            "id": "",
            "report_type": "not-a-type",
            "title": "x",
            "created_at": "now",
            "evidence_status": "not-a-status",
            "sections": [{"title": 5}, "not-an-object"],
        }
    )

    assert any("id" in problem for problem in problems)
    assert any("not-a-type" in problem for problem in problems)
    assert any("not-a-status" in problem for problem in problems)
    assert any("sections[0].title" in problem for problem in problems)
    assert any("sections[0].summary" in problem for problem in problems)
    assert any("sections[1]" in problem for problem in problems)
    assert "sections must be a list" in validate_report_payload(
        {"id": "a", "report_type": "qbr", "title": "t", "created_at": "now", "sections": {}}
    )


def test_export_writes_audit_event_and_missing_report_raises(settings) -> None:
    service = _service(settings)
    report = service.create_report(ReportType.AUDIT_EXPORT, "Audit Snapshot", _sections())

    rendered = service.export_report(report.id, ReportFormat.MARKDOWN)
    events = service.store.list_audit_events()

    assert isinstance(rendered, str) and rendered.startswith("# Audit Snapshot")
    assert any(event.event_type == "report.exported" for event in events)
    try:
        service.export_report("missing-id", ReportFormat.JSON)
        raise AssertionError("missing report must raise")
    except KeyError:
        pass


def test_api_report_list_detail_and_export(settings) -> None:
    service = _service(settings)
    report = service.create_report(
        ReportType.CONNECTOR_HEALTH, "API Report", _sections(), client_id="acme"
    )
    client = TestClient(create_app(settings))

    listing = client.get("/reports")
    filtered = client.get("/reports", params={"report_type": "connector_health"})
    empty = client.get("/reports", params={"report_type": "qbr", "client_id": "acme"})
    detail = client.get(f"/reports/{report.id}")
    exported_json = client.get(f"/reports/{report.id}/export")
    exported_md = client.get(
        f"/reports/{report.id}/export", params={"export_format": "markdown"}
    )
    exported_pdf = client.get(f"/reports/{report.id}/export", params={"export_format": "pdf"})
    missing = client.get("/reports/nope")
    missing_export = client.get("/reports/nope/export")

    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert filtered.json()[0]["id"] == report.id
    assert empty.json() == []
    assert detail.status_code == 200
    assert detail.json()["title"] == "API Report"
    assert exported_json.status_code == 200
    assert exported_json.headers["content-type"].startswith("application/json")
    assert "attachment" in exported_json.headers["content-disposition"]
    assert exported_md.status_code == 200
    assert exported_md.headers["content-type"].startswith("text/markdown")
    assert exported_md.text.startswith("# API Report")
    assert exported_pdf.status_code == 200
    assert exported_pdf.headers["content-type"].startswith("application/pdf")
    assert exported_pdf.headers["content-disposition"].endswith(f'wait-report-{report.id}.pdf"')
    assert exported_pdf.content.startswith(b"%PDF-")
    assert missing.status_code == 404
    assert missing_export.status_code == 404


def test_api_report_routes_require_bearer_token_outside_demo_mode(settings) -> None:
    secured = replace(settings, demo_mode=False, api_token="token-123")
    client = TestClient(create_app(secured))

    unauthorized = client.get("/reports")
    authorized = client.get("/reports", headers={"Authorization": "Bearer token-123"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_cli_reports_list_show_and_export(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_DEMO_MODE", "true")
    service = ReportService(Store(tmp_path / "state.db"))
    report = service.create_report(ReportType.QBR, "CLI Report", _sections(), client_id="acme")
    runner = CliRunner()
    output_path = tmp_path / "exports" / "report.md"
    pdf_output_path = tmp_path / "exports" / "report.pdf"

    listing = runner.invoke(app, ["reports", "list"])
    filtered = runner.invoke(app, ["reports", "list", "--report-type", "qbr"])
    bad_type = runner.invoke(app, ["reports", "list", "--report-type", "nope"])
    shown = runner.invoke(app, ["reports", "show", report.id])
    missing = runner.invoke(app, ["reports", "show", "missing-id"])
    exported = runner.invoke(
        app,
        [
            "reports",
            "export",
            report.id,
            "--export-format",
            "markdown",
            "--output",
            str(output_path),
        ],
    )
    inline = runner.invoke(app, ["reports", "export", report.id])
    bad_format = runner.invoke(app, ["reports", "export", report.id, "--export-format", "nope"])
    missing_export = runner.invoke(app, ["reports", "export", "missing-id"])
    pdf_exported = runner.invoke(
        app,
        ["reports", "export", report.id, "--export-format", "pdf", "--output", str(pdf_output_path)],
    )
    pdf_inline = runner.invoke(app, ["reports", "export", report.id, "--export-format", "pdf"])

    assert listing.exit_code == 0
    assert report.id in listing.output
    assert "count=1" in listing.output
    assert filtered.exit_code == 0
    assert "count=1" in filtered.output
    assert bad_type.exit_code == 1
    assert shown.exit_code == 0
    assert '"title": "CLI Report"' in shown.output
    assert missing.exit_code == 1
    assert exported.exit_code == 0
    assert output_path.read_text(encoding="utf-8").startswith("# CLI Report")
    assert inline.exit_code == 0
    assert '"report_type": "qbr"' in inline.output
    assert bad_format.exit_code == 1
    assert missing_export.exit_code == 1
    assert pdf_exported.exit_code == 0
    assert pdf_output_path.read_bytes().startswith(b"%PDF-")
    assert pdf_inline.exit_code == 1
    assert "requires --output" in pdf_inline.output


def test_cli_generates_recurring_service_review(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    monkeypatch.setenv("WAIT_DEMO_MODE", "true")
    store = Store(data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = 'acme'")

    result = CliRunner().invoke(
        app,
        [
            "reports",
            "recurring-service-review",
            "--period-start",
            "2026-01-01",
            "--period-end",
            "2026-03-31",
            "--client-id",
            "acme",
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"report_type": "recurring_service_review"' in result.output
    assert '"scope": "single client"' in result.output
