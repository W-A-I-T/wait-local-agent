from __future__ import annotations

import json
import re
from dataclasses import asdict
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from wait_local_agent.reports.models import GeneratedReport, ReportFormat

SENSITIVE_KEY_TOKENS = frozenset(
    {
        "key",
        "token",
        "secret",
        "password",
        "passwd",
        "credential",
        "authorization",
        "bearer",
        "private",
    }
)

REDACTED = "[redacted]"

_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(\b(?:secret|token|key|api[_-]?key|password|apikey|auth[_-]?token|"
    r"bearer|authorization|x-api-key|client[_-]?secret|access[_-]?token|"
    r"credential|private[_-]?key)\b\s*[:=]\s*)([^\s,;]+)"
)
_AWS_ACCESS_KEY_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def redact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if _is_sensitive_key(key):
            redacted[key] = REDACTED
        else:
            redacted[key] = redact_value(value)
    return redacted


def _normalized_key_tokens(key: object) -> tuple[str, ...]:
    """Split keys at camel-case and separator boundaries before matching."""

    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", str(key))
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", normalized)
    normalized = re.sub(r"[^A-Za-z0-9]+", " ", normalized).lower()
    return tuple(normalized.split())


def _is_sensitive_key(key: object) -> bool:
    # Exact tokens avoid substring false positives such as ``monkey`` and
    # ``keyboard`` while still matching ``key``, ``api-key``, and ``apiKey``.
    tokens = _normalized_key_tokens(key)
    return bool(SENSITIVE_KEY_TOKENS.intersection(tokens)) or "".join(tokens) in SENSITIVE_KEY_TOKENS


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    """Redact secret-looking key/value pairs in human-readable text."""

    return _AWS_ACCESS_KEY_PATTERN.sub(REDACTED, _SENSITIVE_TEXT_PATTERN.sub(r"\1" + REDACTED, value))


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
        f"- Evidence status: `{payload['evidence_status']}`",
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


def render_pdf(report: GeneratedReport) -> bytes:
    """Render a redacted report as a self-contained local PDF document."""

    payload = report_as_dict(report)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "WaitReportTitle", parent=styles["Title"], alignment=TA_CENTER,
        fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=14,
    )
    heading_style = ParagraphStyle(
        "WaitReportHeading", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=13, leading=16, spaceBefore=10, spaceAfter=6,
    )
    label_style = ParagraphStyle(
        "WaitReportLabel", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=9, leading=12,
    )
    body_style = ParagraphStyle(
        "WaitReportBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9, leading=12, spaceAfter=4,
    )
    small_style = ParagraphStyle(
        "WaitReportSmall", parent=body_style, fontSize=8, leading=10,
        textColor=colors.HexColor("#444444"),
    )

    story: list[Any] = [Paragraph(_pdf_text(payload["title"]), title_style)]
    metadata_rows = [
        ("Report ID", payload["id"]),
        ("Report type", payload["report_type"]),
        ("Evidence status", payload["evidence_status"]),
        ("Created at", payload["created_at"]),
    ]
    for field_name in ("created_by", "client_id", "project_id"):
        if payload[field_name]:
            metadata_rows.append((field_name.replace("_", " ").title(), payload[field_name]))
    metadata_table = Table(
        [
            [Paragraph(_pdf_text(label), label_style), Paragraph(_pdf_value(value), body_style)]
            for label, value in metadata_rows
        ],
        colWidths=[1.35 * inch, 5.65 * inch], hAlign="LEFT",
    )
    metadata_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF0F6")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAB7C4")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DDE5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    story.extend([metadata_table, Spacer(1, 12)])

    for section in payload["sections"]:
        story.extend([
            Paragraph(_pdf_text(section["title"]), heading_style),
            Paragraph(_pdf_text(section["summary"]), body_style),
        ])
        for field_name, heading in (
            ("findings", "Findings"),
            ("evidence", "Evidence"),
            ("recommendations", "Recommendations"),
        ):
            values = section[field_name]
            if not values:
                continue
            story.append(Paragraph(heading, label_style))
            for value in values:
                story.append(Paragraph(f"- {_pdf_value(value)}", body_style))
        story.append(Spacer(1, 4))

    if payload["metadata"]:
        story.extend([
            Paragraph("Metadata", heading_style),
            Paragraph(_pdf_value(payload["metadata"]), small_style),
        ])

    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=letter, rightMargin=0.65 * inch, leftMargin=0.65 * inch,
        topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        title=_pdf_plain_text(payload["title"]), author="WAIT Local Agent",
    )
    document.build(story, onFirstPage=_draw_pdf_footer, onLaterPages=_draw_pdf_footer)
    return output.getvalue()


def render_report(report: GeneratedReport, export_format: ReportFormat) -> str | bytes:
    if export_format is ReportFormat.JSON:
        return render_json(report)
    if export_format is ReportFormat.MARKDOWN:
        return render_markdown(report)
    if export_format is ReportFormat.PDF:
        return render_pdf(report)
    raise ValueError(f"unsupported report format: {export_format.value}")


def _pdf_plain_text(value: object) -> str:
    """Keep built-in Helvetica PDF output deterministic and glyph-safe."""

    return str(value).replace("\u2013", "-").replace("\u2014", "-").encode("ascii", "replace").decode("ascii")


def _pdf_text(value: object) -> str:
    return escape(_pdf_plain_text(value)).replace("\n", "<br/>")


def _pdf_value(value: object) -> str:
    if isinstance(value, str):
        return _pdf_text(value)
    return _pdf_text(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))


def _draw_pdf_footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#66727D"))
    canvas.drawString(document.leftMargin, 0.38 * inch, "WAIT Local Agent - evidence report")
    canvas.drawRightString(letter[0] - document.rightMargin, 0.38 * inch, f"Page {document.page}")
    canvas.restoreState()


def _inline(item: dict[str, Any]) -> str:
    return ", ".join(f"{key}: {value}" for key, value in sorted(item.items()))
