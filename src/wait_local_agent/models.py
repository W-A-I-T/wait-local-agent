from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

ApprovalStatus = Literal["pending", "approved", "rejected"]
ActionKind = Literal[
    "ticket.triage",
    "ticket.assign",
    "ticket.follow_up",
    "ticket.alert",
    "ticket.draft_response",
]
ConnectorKind = Literal["psa", "documentation", "rmm", "m365", "marketplace", "communications"]
ConnectorStatusValue = Literal["not_configured", "configured", "blocked", "ready"]
WorkflowRunStatus = Literal["pending_approval", "approved", "rejected", "completed", "failed"]


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
    document_id: int | None = None
    chunk_id: int | None = None


@dataclass(frozen=True)
class TicketSummary:
    ticket_id: str
    classification: str
    summary: str
    suggested_response: str
    sources: list[SourceReference]
    approval_status: ApprovalStatus = "pending"
    approval_comment: str = ""


@dataclass(frozen=True)
class AuditEvent:
    id: int | None
    event_type: str
    subject_id: str
    detail: str
    created_at: str


@dataclass(frozen=True)
class ApprovalRequest:
    id: int | None
    subject_id: str
    action_type: str
    payload_json: str
    status: ApprovalStatus
    comment: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EventHistoryEntry:
    id: int | None
    event_type: str
    subject_id: str
    status: str
    message: str
    payload_json: str
    created_at: str


@dataclass(frozen=True)
class ConnectorStatus:
    id: str
    kind: ConnectorKind
    name: str
    status: ConnectorStatusValue
    message: str
    write_actions_enabled: bool = False
    http_probing_enabled: bool = False


@dataclass(frozen=True)
class HaloTicketDraft:
    ticket_id: str
    action_type: str
    payload_json: str
    approval_required: bool
    status: ApprovalStatus
    approval_request_id: int | None = None


@dataclass(frozen=True)
class WorkflowTemplate:
    id: str
    name: str
    trigger: str
    description: str
    action_type: ActionKind
    approval_required: bool


@dataclass(frozen=True)
class WorkflowRun:
    id: int | None
    template_id: str
    ticket_id: str
    status: WorkflowRunStatus
    message: str
    approval_request_id: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SecretRecord:
    key: str
    configured: bool
    required_for: str


@dataclass(frozen=True)
class KnowledgeDocument:
    id: int
    path: str
    title: str
    kind: str
    checksum: str
    modified_at: str
    chunk_count: int
    indexed_at: str


@dataclass(frozen=True)
class KnowledgeDocumentWrite:
    path: str
    title: str
    kind: str
    checksum: str
    modified_at: str
    chunks: list[str]


@dataclass(frozen=True)
class KnowledgeChunk:
    id: int
    document_id: int
    title: str
    path: str
    chunk_index: int
    text: str
    excerpt: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
