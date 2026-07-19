from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

ApprovalStatus = Literal["pending", "approved", "rejected"]
HaloWriteStatus = Literal["not_started", "blocked", "not_configured", "succeeded", "failed"]
ActionKind = Literal[
    "ticket.triage",
    "ticket.assign",
    "ticket.follow_up",
    "ticket.alert",
    "ticket.draft_response",
]
ConnectorKind = Literal["psa", "documentation", "rmm", "m365", "marketplace", "communications"]
ConnectorStatusValue = Literal["not_configured", "configured", "blocked", "ready", "failed"]
WorkflowRunStatus = Literal["pending_approval", "approved", "rejected", "completed", "failed"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Ticket:
    id: str
    client: str
    subject: str
    body: str
    priority: str
    status: str
    client_id: str | None = None


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
    client_id: str | None = None
    approver_id: str | None = None


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
    execution_status: HaloWriteStatus = "not_started"
    execution_message: str = ""
    executed_at: str = ""
    execution_result_json: str = "{}"
    client_id: str | None = None
    approver_id: str | None = None


@dataclass(frozen=True)
class EventHistoryEntry:
    id: int | None
    event_type: str
    subject_id: str
    status: str
    message: str
    payload_json: str
    created_at: str
    client_id: str | None = None


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
class HaloReadResult:
    status: ConnectorStatusValue
    message: str
    count: int = 0


ConnectorReadResult = HaloReadResult


@dataclass(frozen=True)
class HaloWriteRequest:
    ticket_id: str
    action_type: str
    fields: dict[str, object]
    approval_request_id: int | None = None


@dataclass(frozen=True)
class HaloWriteResult:
    status: HaloWriteStatus
    message: str
    action_type: str
    ticket_id: str
    endpoint: str = ""
    status_code: int | None = None
    remote_id: str = ""


@dataclass(frozen=True)
class HaloTicket:
    id: str
    summary: str
    status: str
    priority: str
    client_id: str
    client_name: str


@dataclass(frozen=True)
class HaloClient:
    id: str
    name: str
    status: str


@dataclass(frozen=True)
class HaloNote:
    id: str
    ticket_id: str
    body: str
    created_at: str
    is_private: bool


@dataclass(frozen=True)
class HaloAsset:
    id: str
    client_id: str
    name: str
    asset_type: str
    status: str


@dataclass(frozen=True)
class HaloCategory:
    id: str
    name: str
    parent_id: str


@dataclass(frozen=True)
class HuduCompany:
    id: str
    name: str
    archived: bool


@dataclass(frozen=True)
class HuduArticle:
    id: str
    name: str
    company_id: str
    folder_id: str
    updated_at: str
    url: str


@dataclass(frozen=True)
class HuduFolder:
    id: str
    name: str
    company_id: str
    parent_folder_id: str


@dataclass(frozen=True)
class WorkflowTemplate:
    id: str
    name: str
    trigger: str
    description: str
    action_type: ActionKind
    approval_required: bool
    risk_level: RiskLevel = "low"
    preview_fields: tuple[str, ...] = ()


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
    client_id: str | None = None


@dataclass(frozen=True)
class ScheduledJob:
    id: int | None
    template_id: str
    cron: str
    params_json: str
    paused: bool
    created_at: str
    updated_at: str
    client_id: str | None = None
    next_run_at: str | None = None


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
    client_id: str | None = None


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
    client_id: str | None = None


@dataclass(frozen=True)
class CollectorSource:
    id: int | None
    module_id: str
    name: str
    config_json: str
    config_hash: str
    created_at: str
    updated_at: str
    client_id: str | None = None


@dataclass(frozen=True)
class CollectorRun:
    id: int | None
    module_id: str
    source_id: int | None
    status: str
    mode: str
    scope_json: str
    preview_json: str
    result_json: str
    started_at: str
    completed_at: str
    client_id: str | None = None
    actor_id: str | None = None
    report_id: str | None = None


@dataclass(frozen=True)
class CanonicalAsset:
    id: int | None
    canonical_id: str
    asset_type: str
    display_name: str
    attributes_json: str
    first_seen: str
    last_seen: str
    client_id: str | None = None
    owner: str = ""
    source_module: str = ""
    source_id: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class AssetObservation:
    id: int | None
    asset_id: int
    run_id: int
    source_id: int | None
    observed_at: str
    observation_type: str
    payload_json: str
    confidence: float = 1.0


@dataclass(frozen=True)
class ConfigSnapshot:
    id: int | None
    run_id: int
    asset_id: int | None
    source_id: int | None
    snapshot_type: str
    checksum: str
    payload_json: str
    created_at: str


@dataclass(frozen=True)
class ConfigDiff:
    id: int | None
    baseline_snapshot_id: int | None
    candidate_snapshot_id: int | None
    asset_id: int | None
    diff_type: str
    severity: str
    summary: str
    payload_json: str
    created_at: str


@dataclass(frozen=True)
class RestoreExercise:
    id: int | None
    run_id: int | None
    asset_id: int | None
    source_id: int | None
    exercise_id: str
    status: str
    target: str
    backup_artifact_id: str
    validation_json: str
    evidence_json: str
    started_at: str
    completed_at: str
    client_id: str | None = None


@dataclass(frozen=True)
class CollectorAssetWrite:
    canonical_id: str
    asset_type: str
    display_name: str
    attributes: dict[str, Any]
    client_id: str | None = None
    owner: str = ""
    source_module: str = ""
    source_id: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class AssetObservationWrite:
    canonical_id: str
    observation_type: str
    payload: dict[str, Any]
    confidence: float = 1.0


@dataclass(frozen=True)
class ConfigSnapshotWrite:
    snapshot_type: str
    payload: dict[str, Any]
    canonical_id: str | None = None
    checksum: str = ""


@dataclass(frozen=True)
class ConfigDiffWrite:
    diff_type: str
    severity: str
    summary: str
    payload: dict[str, Any]
    baseline_snapshot_id: int | None = None
    candidate_snapshot_id: int | None = None
    canonical_id: str | None = None


@dataclass(frozen=True)
class RestoreExerciseWrite:
    exercise_id: str
    status: str
    target: str
    backup_artifact_id: str
    validation: dict[str, Any]
    evidence: dict[str, Any]
    canonical_id: str | None = None
    started_at: str = ""
    completed_at: str = ""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
