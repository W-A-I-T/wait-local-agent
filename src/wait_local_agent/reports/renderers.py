from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from wait_local_agent.reports.models import GeneratedReport, ReportFormat

SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "api_key",
    "password",
    "apikey",
    "auth_token",
    "bearer",
    "authorization",
    "x-api-key",
    "client_secret",
    "access_token",
    "credential",
    "private_key",
)

REDACTED = "[redacted]"


def redact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
            redacted[key] = REDACTED
        else:
            redacted[key] = redact_value(value)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def report_as_dict(report: GeneratedReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["report_type"] = report.report_type.value
    return redact_mapping(payload)


def render_json(report: GeneratedReport) -> str:
    return json.dumps(report_as_dict(report), sort_keys=True, indent=2) + "\n"


def render_markdown(report: GeneratedReport) -> str:
    payload = report_as_dict(report)
    lines: list[str] = [
        f"# {payload['title']}",
        "",
        f"- Report ID: `{payload['id']}`",
        f"- Report type: `{payload['report_type']}`",
        f"- Created at: {payload['created_at']}",
    ]
    if payload["created_by"]:
        lines.append(f"- Created by: {payload['created_by']}")
    if payload["client_id"]:
        lines.append(f"- Client: {payload['client_id']}")
    if payload["project_id"]:
        lines.append(f"- Project: {payload['project_id']}")
    for section in payload["sections"]:
        lines.extend(["", f"## {section['title']}", "", section["summary"]])
        if section["findings"]:
            lines.extend(["", "### Findings", ""])
            lines.extend(f"- {_inline(item)}" for item in section["findings"])
        if section["evidence"]:
            lines.extend(["", "### Evidence", ""])
            lines.extend(f"- {_inline(item)}" for item in section["evidence"])
        if section["recommendations"]:
            lines.extend(["", "### Recommendations", ""])
            lines.extend(f"- {item}" for item in section["recommendations"])
    if payload["metadata"]:
        lines.extend(["", "## Metadata", "", f"`{json.dumps(payload['metadata'], sort_keys=True)}`"])
    return "\n".join(lines) + "\n"


def render_report(report: GeneratedReport, export_format: ReportFormat) -> str:
    if export_format is ReportFormat.JSON:
        return render_json(report)
    if export_format is ReportFormat.MARKDOWN:
        return render_markdown(report)
    raise ValueError(f"report format {export_format.value} is not available in the open core yet")


def _inline(item: dict[str, Any]) -> str:
    return ", ".join(f"{key}: {value}" for key, value in sorted(item.items()))
