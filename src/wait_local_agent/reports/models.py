from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from wait_local_agent.models import utc_now


class ReportType(StrEnum):
    TICKET_INTELLIGENCE = "ticket_intelligence"
    APPROVAL_EXECUTION = "approval_execution"
    CONNECTOR_HEALTH = "connector_health"
    AUDIT_EXPORT = "audit_export"
    QBR = "qbr"
    AUTOMATION_OPPORTUNITY = "automation_opportunity"
    FOUNDER_PREFLIGHT = "founder_preflight"
    DEVELOPER_HANDOFF = "developer_handoff"
    COLLECTOR_BUNDLE = "collector_bundle"
    INVESTOR_EVIDENCE = "investor_evidence"
    LICENSE_ENTITLEMENT = "license_entitlement"
    APPLIANCE_HARDENING = "appliance_hardening"


class ReportFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    PDF = "pdf"


@dataclass(frozen=True)
class ReportSection:
    title: str
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GeneratedReport:
    id: str
    report_type: ReportType
    title: str
    created_at: str
    created_by: str
    client_id: str
    project_id: str
    sections: list[ReportSection]
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new(
        report_type: ReportType,
        title: str,
        sections: list[ReportSection],
        created_by: str = "",
        client_id: str = "",
        project_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GeneratedReport:
        return GeneratedReport(
            id=str(uuid4()),
            report_type=report_type,
            title=title,
            created_at=utc_now(),
            created_by=created_by,
            client_id=client_id,
            project_id=project_id,
            sections=sections,
            metadata=metadata or {},
        )

    def sections_json(self) -> str:
        return json.dumps([asdict(section) for section in self.sections], sort_keys=True)

    def metadata_json(self) -> str:
        return json.dumps(self.metadata, sort_keys=True)


def sections_from_json(payload: str) -> list[ReportSection]:
    raw = json.loads(payload)
    if not isinstance(raw, list):
        raise ValueError("sections payload must be a JSON list")
    return [ReportSection(**item) for item in raw]
