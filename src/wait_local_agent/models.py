from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]
HaloWriteStatus = Literal["not_started", "blocked", "not_configured", "succeeded", "failed"]
ConnectWiseWriteStatus = Literal[
    "not_started", "blocked", "not_configured", "succeeded", "failed"
]
ServiceNowWriteStatus = Literal[
    "not_started", "blocked", "not_configured", "succeeded", "failed"
]
AutotaskWriteStatus = Literal[
    "not_started", "blocked", "not_configured", "succeeded", "failed"
]
SyncroWriteStatus = Literal[
    "not_started", "blocked", "not_configured", "succeeded", "failed"
]
ActionKind = Literal[
    "ticket.triage",
    "ticket.assign",
    "ticket.follow_up",
    "ticket.alert",
    "ticket.draft_response",
    "ticket.quality",
    "ticket.sentiment",
    "ticket.escalation",
    "ticket.similar",
    "ticket.security_alert",
    "ticket.l1_resolution",
    "ticket.duplicate_review",
    "ticket.sla_assessment",
    "ticket.stale_sweep",
    "m365.user_onboarding",
    "m365.user_offboarding",
    "m365.password_reset",
    "m365.authentication_method_removal",
    "m365.license_request",
    "m365.compliance_review",
    "m365.inactive_license_review",
    "rmm.software_inventory_review",
    "client.recurring_service_review",
]
ConnectorKind = Literal["psa", "documentation", "rmm", "m365", "marketplace", "communications"]
ConnectorStatusValue = Literal["not_configured", "configured", "blocked", "ready", "failed"]
WorkflowRunStatus = Literal["pending_approval", "approved", "rejected", "completed", "failed"]
RiskLevel = Literal["low", "medium", "high"]
AgentRunStatus = Literal[
    "queued",
    "pending_approval",
    "completed",
    "failed",
    "rejected",
    "cancelled",
]
AGENT_BACKFILL_MAX_CONCURRENCY = 4
DEFAULT_APPROVAL_EXPIRY_SECONDS = 24 * 60 * 60
MAX_APPROVAL_EXPIRY_SECONDS = 30 * 24 * 60 * 60
DEFAULT_EVENT_MAX_RETRIES = 3
DEFAULT_EVENT_RETRY_DELAY_SECONDS = 60
MAX_EVENT_RETRY_DELAY_SECONDS = 60 * 60
MAX_EVENT_RETRIES = 10
EVENT_RETRY_POLL_SECONDS = 30
EVENT_RETRY_BATCH_SIZE = 10


@dataclass(frozen=True)
class Client:
    client_id: str
    name: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConnectorInstance:
    connector_instance_id: str
    connector_type: str
    display_name: str
    client_id: str | None
    credential_ref: str | None
    config_json: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ClientConnectorMapping:
    mapping_id: str
    connector_instance_id: str
    external_company_id: str
    external_company_name: str | None
    client_id: str
    verified: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Ticket:
    id: str
    client: str
    subject: str
    body: str
    priority: str
    status: str
    client_id: str | None = None
    requester_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TicketNote:
    id: int | None
    ticket_id: str
    client_id: str
    author: str
    body: str
    created_at: str


@dataclass(frozen=True)
class EndUserMessage:
    id: int | None
    ticket_id: str
    client_id: str
    requester_id: str
    author_role: str
    author_id: str
    body: str
    created_at: str


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
    expires_at: str | None = None


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
class EventDelivery:
    id: int | None
    idempotency_key: str
    event_type: str
    entity_type: str
    entity_id: str
    payload_json: str
    status: str
    matched_agent_count: int
    agent_ids_json: str
    run_ids_json: str
    error_detail: str
    received_at: str
    processed_at: str
    client_id: str | None = None
    agent_attempts_json: str = "{}"
    retry_count: int = 0
    max_retries: int = DEFAULT_EVENT_MAX_RETRIES
    retry_delay_seconds: int = DEFAULT_EVENT_RETRY_DELAY_SECONDS
    next_retry_at: str | None = None
    matched_playbook_count: int = 0
    playbook_ids_json: str = "[]"
    playbook_run_ids_json: str = "[]"
    playbook_attempts_json: str = "{}"


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
class ConnectWiseTicketDraft:
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
class ConnectWiseWriteRequest:
    ticket_id: str
    action_type: str
    fields: dict[str, object]
    approval_request_id: int | None = None


@dataclass(frozen=True)
class ServiceNowWriteRequest:
    ticket_id: str
    action_type: str
    fields: dict[str, object]
    approval_request_id: int | None = None


@dataclass(frozen=True)
class AutotaskWriteRequest:
    ticket_id: str
    action_type: str
    fields: dict[str, object]
    approval_request_id: int | None = None


@dataclass(frozen=True)
class SyncroWriteRequest:
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
class ConnectWiseWriteResult:
    status: ConnectWiseWriteStatus
    message: str
    action_type: str
    ticket_id: str
    endpoint: str = ""
    status_code: int | None = None
    remote_id: str = ""


@dataclass(frozen=True)
class ServiceNowWriteResult:
    status: ServiceNowWriteStatus
    message: str
    action_type: str
    ticket_id: str
    endpoint: str = ""
    status_code: int | None = None
    remote_id: str = ""


@dataclass(frozen=True)
class AutotaskWriteResult:
    status: AutotaskWriteStatus
    message: str
    action_type: str
    ticket_id: str
    endpoint: str = ""
    status_code: int | None = None
    remote_id: str = ""


@dataclass(frozen=True)
class SyncroWriteResult:
    status: SyncroWriteStatus
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
    content: str = ""


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
    tool_id: str | None = None
    payload_schema: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateGalleryEntry:
    id: str
    source_template_id: str
    name: str
    trigger: str
    description: str
    action_type: str
    approval_required: bool
    risk_level: str
    preview_fields_json: str
    provenance: str
    instructions: str
    enabled: bool
    version: int
    created_at: str
    updated_at: str
    client_id: str | None = None
    definition_json: str = "{}"


@dataclass(frozen=True)
class TemplateGalleryRevision:
    id: int
    gallery_id: str
    version: int
    definition_json: str
    created_at: str
    client_id: str | None = None


@dataclass(frozen=True)
class MspPlaybookEntry:
    id: str
    source_playbook_id: str
    definition_json: str
    provenance: str
    enabled: bool
    version: int
    created_at: str
    updated_at: str
    client_id: str | None = None


@dataclass(frozen=True)
class MspPlaybookRevision:
    id: int
    playbook_id: str
    version: int
    snapshot_json: str
    created_at: str
    client_id: str | None = None


@dataclass(frozen=True)
class MspPlaybookSubscription:
    id: str
    playbook_id: str
    event_type: str
    client_id: str
    input_mapping_json: str
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class BlueprintAgent:
    id: str
    name: str
    purpose: str
    tools: tuple[str, ...] = ()
    knowledge: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlueprintWorkflow:
    id: str
    name: str
    trigger: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class SolutionBlueprint:
    id: str
    client_id: str
    created_by: str
    created_at: str
    updated_at: str
    solution_name: str
    business_goal: dict[str, str | bool | int]
    users: tuple[str, ...]
    knowledge: tuple[str, ...]
    systems: tuple[str, ...]
    agents: tuple[BlueprintAgent, ...]
    workflows: tuple[BlueprintWorkflow, ...]
    approvals: dict[str, str]
    deployment: tuple[str, ...]
    risk: RiskLevel
    instructions: str = ""
    intents: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    model: str = ""
    orchestration: str = ""
    environment: tuple[dict[str, object], ...] = ()
    discovery: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsultantDiscoverySession:
    id: str
    client_id: str
    principal_id: str
    status: str
    answers_json: str
    transcript_json: str
    blueprint_id: str | None
    created_at: str
    updated_at: str


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
    template_version: int | None = None


@dataclass(frozen=True)
class TechnicianChatSession:
    id: str
    client_id: str
    principal_id: str
    status: str
    ticket_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TechnicianChatMessage:
    id: int | None
    session_id: str
    role: Literal["user", "assistant"]
    message: str
    action_id: str | None
    status: str
    ticket_id: str | None
    created_at: str


@dataclass(frozen=True)
class SmartActionRun:
    id: int | None
    action_id: str
    actor: str
    status: str
    payload_digest: str
    output_json: str
    evidence_json: str
    approval_id: int | None
    created_at: str
    updated_at: str
    client_id: str | None = None
    error_detail: str = ""


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
    job_kind: str = "workflow"
    agent_id: str | None = None
    entity_id: str | None = None
    schedule_type: str = "cron"
    interval_seconds: int | None = None
    run_at: str | None = None
    timezone: str = "UTC"


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


@dataclass(frozen=True)
class ExecutionRun:
    id: int | None
    run_kind: str
    source_run_id: int | None
    actor: str
    status: str
    started_at: str
    finished_at: str
    trigger_source: str
    client_id: str | None = None
    metadata_json: str = "{}"


@dataclass(frozen=True)
class ExecutionStep:
    id: int | None
    execution_run_id: int
    ordinal: int
    kind: str
    name: str
    status: str
    started_at: str
    finished_at: str
    input_digest: str
    output_digest: str
    input_json: str
    output_json: str
    error_detail: str = ""


@dataclass(frozen=True)
class ExecutionArtifact:
    id: int | None
    execution_run_id: int
    step_ordinal: int | None
    name: str
    media_type: str
    byte_size: int
    sha256: str
    storage_path: str


@dataclass(frozen=True)
class RmmExecutionScope:
    execution_id: str
    provider_id: str
    script_id: str
    device_id: str
    client_id: str
    created_at: str


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    description: str
    enabled: bool
    trigger: str
    entity_type: str
    filters: dict[str, object]
    enabled_tools: list[str]
    steps: list[dict[str, object]]
    max_steps: int
    execution_timeout_seconds: float
    client_id: str | None
    version: int
    created_at: str
    updated_at: str
    run_once_per_entity: bool = True
    depends_on_agent_ids: list[str] = field(default_factory=list)
    execution_window_start: str | None = None
    execution_window_end: str | None = None
    execution_window_timezone: str = "UTC"
    context_sources: list[str] = field(default_factory=list)
    approval_expiry_seconds: int | None = None
    result_aware: bool = False
    approval_required_tools: list[str] = field(default_factory=list)
    approval_rules: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentDefinitionRevision:
    id: int | None
    agent_id: str
    version: int
    definition_json: str
    created_at: str
    client_id: str | None = None


@dataclass(frozen=True)
class AgentRun:
    id: int | None
    agent_id: str
    entity_id: str
    actor: str
    status: AgentRunStatus
    current_step: int
    state_json: str
    started_at: str
    finished_at: str
    revision_version: int | None = None
    client_id: str | None = None


@dataclass(frozen=True)
class AgentBackfill:
    id: int | None
    agent_id: str
    entity_ids_json: str
    input_json: str
    max_concurrency: int
    status: str
    next_index: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    run_ids_json: str
    failed_entity_ids_json: str
    actor: str
    error_detail: str
    created_at: str
    updated_at: str
    client_id: str | None = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
