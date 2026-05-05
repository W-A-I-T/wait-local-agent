from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

ApprovalStatus = Literal["pending", "approved", "rejected"]


@dataclass(frozen=True)
class Ticket:
    id: str
    client: str
    subject: str
    body: str
    priority: str
    status: str


@dataclass(frozen=True)
class SourceReference:
    title: str
    path: str
    excerpt: str


@dataclass(frozen=True)
class TicketSummary:
    ticket_id: str
    classification: str
    summary: str
    suggested_response: str
    sources: list[SourceReference]
    approval_status: ApprovalStatus = "pending"


@dataclass(frozen=True)
class AuditEvent:
    id: int | None
    event_type: str
    subject_id: str
    detail: str
    created_at: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()

