from __future__ import annotations

from typing import Any

from wait_local_agent.reports.models import GeneratedReport, ReportFormat, ReportSection, ReportType
from wait_local_agent.reports.renderers import render_report
from wait_local_agent.store import Store


class ReportService:
    """Create, list, fetch, and export stored reports with audit trail coverage."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def create_report(
        self,
        report_type: ReportType,
        title: str,
        sections: list[ReportSection],
        created_by: str = "",
        client_id: str = "",
        project_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GeneratedReport:
        report = GeneratedReport.new(
            report_type=report_type,
            title=title,
            sections=sections,
            created_by=created_by,
            client_id=client_id,
            project_id=project_id,
            metadata=metadata,
        )
        self.store.save_report(report)
        self.store.add_audit_event("report.created", report.id, f"{report_type.value}: {title}")
        return report

    def get_report(self, report_id: str) -> GeneratedReport | None:
        return self.store.get_report(report_id)

    def list_reports(
        self,
        report_type: ReportType | None = None,
        client_id: str = "",
        project_id: str = "",
    ) -> list[GeneratedReport]:
        return self.store.list_reports(
            report_type=report_type.value if report_type else "",
            client_id=client_id,
            project_id=project_id,
        )

    def export_report(self, report_id: str, export_format: ReportFormat) -> str:
        report = self.store.get_report(report_id)
        if report is None:
            raise KeyError(report_id)
        rendered = render_report(report, export_format)
        self.store.add_audit_event(
            "report.exported",
            report.id,
            f"{report.report_type.value} exported as {export_format.value}",
        )
        return rendered
