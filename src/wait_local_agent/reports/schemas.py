from __future__ import annotations

from typing import Any

from wait_local_agent.reports.models import ReportType

REPORT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GeneratedReport",
    "type": "object",
    "required": ["id", "report_type", "title", "created_at", "sections"],
    "properties": {
        "id": {"type": "string"},
        "report_type": {"type": "string", "enum": [item.value for item in ReportType]},
        "title": {"type": "string"},
        "created_at": {"type": "string"},
        "created_by": {"type": "string"},
        "client_id": {"type": "string"},
        "project_id": {"type": "string"},
        "metadata": {"type": "object"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "summary"],
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "findings": {"type": "array", "items": {"type": "object"}},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "recommendations": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def validate_report_payload(payload: dict[str, Any]) -> list[str]:
    """Return a list of validation problems. Empty list means the payload is valid."""

    problems: list[str] = []
    for key in ("id", "report_type", "title", "created_at"):
        if not isinstance(payload.get(key), str) or not payload.get(key):
            problems.append(f"{key} must be a non-empty string")
    report_type = payload.get("report_type")
    if isinstance(report_type, str) and report_type not in {item.value for item in ReportType}:
        problems.append(f"report_type {report_type} is not a known report type")
    sections = payload.get("sections")
    if not isinstance(sections, list):
        problems.append("sections must be a list")
        return problems
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            problems.append(f"sections[{index}] must be an object")
            continue
        for key in ("title", "summary"):
            if not isinstance(section.get(key), str):
                problems.append(f"sections[{index}].{key} must be a string")
    return problems
