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


@dataclass(frozen=True)
class AuditEvent:
    id: int | None
    event_type: str
    subject_id: str
    detail: str
    created_at: str


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
