"""Request and response models for the local API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from wait_local_agent.models import (
    AGENT_BACKFILL_MAX_CONCURRENCY,
    DEFAULT_EVENT_MAX_RETRIES,
    DEFAULT_EVENT_RETRY_DELAY_SECONDS,
    MAX_APPROVAL_EXPIRY_SECONDS,
    MAX_EVENT_RETRIES,
    MAX_EVENT_RETRY_DELAY_SECONDS,
    MAX_KNOWLEDGE_SOP_VERSION_LENGTH,
    KnowledgeAuthority,
)


class ApprovalRequest(BaseModel):
    status: Literal["approved", "rejected", "pending"]
    comment: str = ""


class KnowledgeIngestRequest(BaseModel):
    path: str
    parser: str | None = None
    ocr: bool | None = None
    client_id: str | None = None


class KnowledgeAuthorityRequest(BaseModel):
    authority: KnowledgeAuthority
    sop_version: str | None = Field(default=None, max_length=MAX_KNOWLEDGE_SOP_VERSION_LENGTH)
    superseded_by: int | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid")


class ApprovalPayloadPatchRequest(BaseModel):
    fields: dict[str, object]
    comment: str = "Draft edited before approval"


class HaloDraftRequest(BaseModel):
    action_type: Literal[
        "add_note",
        "update_status",
        "assign_technician",
        "draft_response",
        "update_ticket_fields",
    ]
    fields: dict[str, object]
    client_id: str | None = None


class ConnectWiseDraftRequest(BaseModel):
    action_type: Literal["update_status", "assign_technician", "update_ticket_fields"]
    fields: dict[str, object]
    client_id: str | None = None


class M365UserDraftRequest(BaseModel):
    user_principal_name: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=256)
    mail_nickname: str = Field(min_length=1, max_length=64)
    temporary_vault_name: str = Field(min_length=14, max_length=128)
    account_enabled: bool = True
    force_change_password_next_sign_in: bool = True
    client_id: str | None = None


class M365UserDisableDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365PasswordResetDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    temporary_vault_name: str = Field(min_length=14, max_length=128)
    force_change_password_next_sign_in: bool = True
    force_change_password_next_sign_in_with_mfa: bool = False
    client_id: str | None = None


class M365AuthenticationMethodDeleteDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    method_type: Literal["fido2", "microsoft_authenticator", "phone", "software_oath"]
    method_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365GroupMembershipDraftRequest(BaseModel):
    group_id: str = Field(min_length=1, max_length=320)
    user_id: str = Field(min_length=1, max_length=320)
    operation: Literal["add", "remove"]
    client_id: str | None = None


class M365LicenseChangeDraftRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=320)
    sku_ids: list[str] = Field(min_length=1, max_length=50)
    operation: Literal["add", "remove"]
    client_id: str | None = None


class M365SessionRevocationDraftRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceRetirementDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceSyncDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceRebootDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365ManagedDeviceRemoteLockDraftRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365MailboxSettingsUpdateDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    settings: dict[str, str] = Field(min_length=1, max_length=4)
    client_id: str | None = None


class M365MailMessageMoveDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    source_folder_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=320)
    destination_folder_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class M365MailMessageReadStateDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    source_folder_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=320)
    is_read: bool
    client_id: str | None = None


class M365MailMessageDeleteDraftRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=320)
    source_folder_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=320)
    client_id: str | None = None


class WorkflowRunRequest(BaseModel):
    ticket_id: str
    client_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class MspPlaybookRunRequest(BaseModel):
    ticket_id: str | None = None
    client_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class MspPlaybookEntryCreateRequest(BaseModel):
    source_playbook_id: str = Field(min_length=1, max_length=120)
    provenance: str = Field(min_length=1, max_length=1000)
    definition: dict[str, object] | None = None
    enabled: bool = True
    client_id: str | None = None


class MspPlaybookEntryUpdateRequest(BaseModel):
    definition: dict[str, object] | None = None
    provenance: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None


class MspPlaybookSubscriptionCreateRequest(BaseModel):
    playbook_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=120)
    input_mapping: dict[str, object] = Field(default_factory=dict, max_length=16)
    enabled: bool = True
    client_id: str | None = None
    model_config = ConfigDict(extra="forbid")


class MspPlaybookSubscriptionUpdateRequest(BaseModel):
    input_mapping: dict[str, object] | None = Field(default=None, max_length=16)
    enabled: bool | None = None
    model_config = ConfigDict(extra="forbid")


class TemplateGalleryCreateRequest(BaseModel):
    source_template_id: str
    provenance: str = Field(min_length=1, max_length=1000)
    display_name: str | None = Field(default=None, max_length=120)
    instructions: str = Field(default="", max_length=4000)
    definition: dict[str, object] | None = None
    client_id: str | None = None


class TemplateGalleryImportRequest(BaseModel):
    format: Literal["wait-local-agent.workflow-template"]
    format_version: Literal[1]
    source_template_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    provenance: str = Field(min_length=1, max_length=1000)
    instructions: str = Field(default="", max_length=4000)
    definition: dict[str, object] | None = None
    client_id: str | None = None


class TemplateGalleryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    instructions: str | None = Field(default=None, max_length=4000)
    definition: dict[str, object] | None = None
    enabled: bool | None = None
    client_id: str | None = None


class TemplateGalleryRestoreRequest(BaseModel):
    client_id: str | None = None


class SolutionBlueprintRequest(BaseModel):
    solution: dict[str, object]
    business_goal: dict[str, object]
    users: list[object]
    knowledge: list[object]
    systems: list[object]
    agents: list[dict[str, object]]
    workflows: list[dict[str, object]]
    approvals: dict[str, object]
    deployment: list[object]
    risk: str
    instructions: str = Field(default="", max_length=4000)
    intents: list[object] = Field(default_factory=list, max_length=32)
    skills: list[object] = Field(default_factory=list, max_length=32)
    model: str = Field(default="", max_length=240)
    orchestration: str = Field(default="", max_length=32)
    environment: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    discovery: dict[str, object] = Field(default_factory=dict)
    client_id: str | None = None
    model_config = ConfigDict(extra="forbid")


class OpenApiConnectorRequest(BaseModel):
    connector_id: str = Field(min_length=1, max_length=64)
    definition: dict[str, object]


class EvaluationExecutionRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    entity_id: str = Field(min_length=1, max_length=100)
    client_id: str = Field(min_length=1, max_length=128)
    input: dict[str, object] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class EvaluationRequest(BaseModel):
    test_set: list[dict[str, object]]
    observations: dict[str, object] = Field(default_factory=dict)
    execution: EvaluationExecutionRequest | None = None

    model_config = ConfigDict(extra="forbid")


class EmployeeOnboardingDemoRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(default="TCK-1001", min_length=1, max_length=100)
    blueprint_id: str | None = Field(default=None, min_length=1, max_length=64)
    blueprint: dict[str, object] | None = Field(default=None, max_length=32)
    output_directory: str | None = Field(default=None, min_length=1, max_length=240)

    model_config = ConfigDict(extra="forbid")


class GovernanceRequest(BaseModel):
    architecture: dict[str, object]
    connector_artifacts: list[dict[str, object]] = Field(default_factory=list, max_length=16)


class PowerAppsPlanRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    app_name: str = Field(min_length=1, max_length=120)
    entities: list[dict[str, object]] = Field(default_factory=list, max_length=16)
    screens: list[dict[str, object]] = Field(default_factory=list, max_length=16)
    actions: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    model_config = ConfigDict(extra="forbid")


class PowerPlatformPackageRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    solution_name: str = Field(min_length=1, max_length=64)
    publisher_name: str = Field(min_length=1, max_length=100)
    publisher_prefix: str = Field(min_length=2, max_length=8)
    output_directory: str = Field(min_length=1, max_length=240)
    artifacts: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    connector_artifacts: list[dict[str, object]] = Field(default_factory=list, max_length=16)

    model_config = ConfigDict(extra="forbid")


class PowerPlatformPackageValidationRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=128)
    package: dict[str, object]

    model_config = ConfigDict(extra="forbid")


class PowerPlatformPackageMaterializationRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=128)
    package: dict[str, object]

    model_config = ConfigDict(extra="forbid")


class PowerAutomatePlanRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=64)
    workflow_name: str = Field(min_length=1, max_length=240)
    trigger: str = Field(min_length=1, max_length=240)
    steps: list[dict[str, object]] = Field(min_length=1, max_length=32)
    model_config = ConfigDict(extra="forbid")


class CopilotStudioPlanRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    copilot_name: str = Field(min_length=1, max_length=240)
    business_goal: str = Field(min_length=1, max_length=500)
    topics: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    knowledge_sources: list[object] = Field(default_factory=list, max_length=32)
    actions: list[dict[str, object]] = Field(default_factory=list, max_length=32)

    model_config = ConfigDict(extra="forbid")


class DiscoveryRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    answers: dict[str, object] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class DiscoveryBlueprintPromotionRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    solution_name: str = Field(min_length=1, max_length=240)
    risk: Literal["low", "medium", "high"]
    answers: dict[str, object] = Field(default_factory=dict, max_length=28)

    model_config = ConfigDict(extra="forbid")


class DiscoverySessionStartRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    opening_message: str | None = Field(default=None, max_length=2000)
    answers: dict[str, object] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class DiscoveryTurnRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    field: str = Field(min_length=1, max_length=64)
    answer: object
    model_config = ConfigDict(extra="forbid")


class EnvironmentDiscoveryRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    systems: list[object] = Field(default_factory=list, max_length=32)
    probe: bool = False

    model_config = ConfigDict(extra="forbid")


class SupervisorPlanRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=2000)
    child_agent_ids: list[str] = Field(min_length=1, max_length=8)
    max_retries: int = Field(default=0, ge=0, le=3)
    model_config = ConfigDict(extra="forbid")


class SupervisorRunRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=100)
    task: str = Field(min_length=1, max_length=2_000)
    child_agent_ids: list[str] = Field(min_length=1, max_length=8)
    input: dict[str, object] = Field(default_factory=dict, max_length=16)
    completed_run_ids: list[int] = Field(default_factory=list, max_length=8)
    max_retries: int = Field(default=0, ge=0, le=3)
    cancel_run_id: int | None = Field(default=None, ge=1)
    model_config = ConfigDict(extra="forbid")


class DeliveryPlanRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    architecture: dict[str, object]
    evaluation: dict[str, object]
    governance: dict[str, object]
    deployment_targets: list[str] = Field(min_length=1, max_length=8)
    connector_artifacts: list[dict[str, object]] = Field(default_factory=list, max_length=16)
    review_artifacts: list[dict[str, object]] = Field(default_factory=list, max_length=16)
    deployable_package: dict[str, object] | None = None
    model_config = ConfigDict(extra="forbid")


class PowerPlatformDeploymentRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    solution_name: str = Field(min_length=1, max_length=64)
    publisher_name: str = Field(min_length=1, max_length=100)
    publisher_prefix: str = Field(min_length=2, max_length=8)
    output_directory: str = Field(min_length=1, max_length=240)
    deployment_targets: list[dict[str, object]] = Field(min_length=1, max_length=3)
    stage: Literal["build", "dev", "test", "prod"] = "build"
    promotion_evidence: dict[str, object] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class PowerPlatformRollbackRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    solution_name: str = Field(min_length=1, max_length=64)
    publisher_name: str = Field(min_length=1, max_length=100)
    publisher_prefix: str = Field(min_length=2, max_length=8)
    output_directory: str = Field(min_length=1, max_length=240)
    deployment_targets: list[dict[str, object]] = Field(min_length=1, max_length=3)
    stage: Literal["dev", "test", "prod"]
    rollback_artifact_path: str = Field(min_length=1, max_length=240)
    rollback_evidence: dict[str, object]
    model_config = ConfigDict(extra="forbid")


class TeamsMessageDraftRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=320)
    channel_id: str = Field(min_length=1, max_length=320)
    body: str = Field(min_length=1, max_length=4000)
    client_id: str | None = Field(default=None, max_length=128)
    model_config = ConfigDict(extra="forbid")


class SmartActionInvokeRequest(BaseModel):
    payload: dict[str, object] = Field(default_factory=dict)
    confirm: bool = False
    client_id: str | None = None


class TechnicianChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    ticket_id: str | None = Field(default=None, max_length=100)
    client_id: str | None = None


class TechnicianChatSessionCreateRequest(BaseModel):
    ticket_id: str | None = Field(default=None, max_length=100)
    client_id: str | None = None


class TechnicianChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    ticket_id: str | None = Field(default=None, max_length=100)


class EndUserTicketCreateRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)


class EndUserBrandingResponse(BaseModel):
    brand_name: str
    brand_tagline: str
    brand_logo_data_uri: str
    brand_accent_color: str
    brand_surface_color: str


class EndUserMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class EndUserHaloSyncDraftRequest(BaseModel):
    external_ticket_id: str = Field(min_length=1, max_length=100)


class ClientReportRequest(BaseModel):
    period_start: date
    period_end: date
    client_id: str | None = Field(default=None, min_length=1, max_length=200)


class AgentStepRequest(BaseModel):
    tool_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    failure_policy: dict[str, object] | None = None


class AgentApprovalRuleRequest(BaseModel):
    tool_id: str = Field(min_length=1, max_length=120)
    when: dict[str, list[str]] = Field(min_length=1, max_length=3)


class AgentDefinitionRequest(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    trigger: Literal["manual", "scheduled", "event"] = "manual"
    entity_type: Literal["ticket"] = "ticket"
    filters: dict[str, object] = Field(default_factory=dict)
    enabled_tools: list[str]
    steps: list[AgentStepRequest]
    max_steps: int = Field(default=8, ge=1, le=8)
    execution_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    client_id: str | None = None
    run_once_per_entity: bool = True
    depends_on_agent_ids: list[str] = Field(default_factory=list)
    execution_window_start: str | None = Field(default=None, max_length=5)
    execution_window_end: str | None = Field(default=None, max_length=5)
    execution_window_timezone: str = Field(default="UTC", min_length=1, max_length=100)
    context_sources: list[Literal["ticket", "client", "knowledge"]] = Field(default_factory=list, max_length=3)
    approval_expiry_seconds: int | None = Field(default=None, ge=1, le=MAX_APPROVAL_EXPIRY_SECONDS)
    result_aware: bool = False
    approval_required_tools: list[str] = Field(default_factory=list, max_length=8)
    approval_rules: list[AgentApprovalRuleRequest] = Field(default_factory=list, max_length=8)


class AgentRunStartRequest(BaseModel):
    entity_id: str
    input: dict[str, object] = Field(default_factory=dict)
    client_id: str | None = None


class AgentPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2_000)
    entity_id: str = Field(min_length=1, max_length=100)
    max_steps: int = Field(default=8, ge=1, le=8)
    client_id: str | None = None


class AgentBackfillCreateRequest(BaseModel):
    agent_id: str
    entity_ids: list[str] = Field(min_length=1, max_length=100)
    input: dict[str, object] = Field(default_factory=dict)
    max_concurrency: int = Field(default=1, ge=1, le=AGENT_BACKFILL_MAX_CONCURRENCY)
    client_id: str | None = None


class AgentBackfillPreviewRequest(BaseModel):
    agent_id: str
    entity_ids: list[str] = Field(min_length=1, max_length=100)
    input: dict[str, object] = Field(default_factory=dict)
    max_concurrency: int = Field(default=1, ge=1, le=AGENT_BACKFILL_MAX_CONCURRENCY)
    client_id: str | None = None


class EventIngestRequest(BaseModel):
    event_type: str
    entity_type: Literal["ticket"] = "ticket"
    entity_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = None
    client_id: str | None = None
    max_retries: int = Field(default=DEFAULT_EVENT_MAX_RETRIES, ge=0, le=MAX_EVENT_RETRIES)
    retry_delay_seconds: int = Field(
        default=DEFAULT_EVENT_RETRY_DELAY_SECONDS,
        ge=1,
        le=MAX_EVENT_RETRY_DELAY_SECONDS,
    )


class ScheduledJobCreateRequest(BaseModel):
    template_id: str | None = None
    report_type: Literal["qbr", "automation_opportunity", "recurring_service_review"] | None = None
    playbook_id: str | None = None
    agent_id: str | None = None
    job_kind: Literal[
        "workflow", "playbook", "agent", "report", "connector_poll", "graph_sync", "baseline_snapshot", "backup"
    ] | None = None
    graph_sync: bool = False
    entity_id: str | None = None
    cron: str = ""
    schedule_type: Literal["cron", "interval", "once"] = "cron"
    interval_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    run_at: str | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    params: dict[str, object] = Field(default_factory=dict)


class ScheduledJobRescheduleRequest(BaseModel):
    cron: str = ""
    schedule_type: Literal["cron", "interval", "once"] = "cron"
    interval_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    run_at: str | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)


class CollectorConfigRequest(BaseModel):
    config: dict[str, object] = Field(default_factory=dict)
    client_id: str | None = None


class CollectorRunRequest(CollectorConfigRequest):
    confirm: bool = False


class PackInstallRequest(BaseModel):
    tarball_path: str = Field(validation_alias=AliasChoices("tarball_path", "tarball"))
    license_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("license_key", "license"),
    )

    model_config = ConfigDict(populate_by_name=True)


class BackupCreateRequest(BaseModel):
    destination: str
    encrypt: bool = False


class BackupRestoreRequest(BaseModel):
    source: str
    encrypted: bool = False


class HardeningRunRequest(BaseModel):
    backup_paths: list[str] = Field(default_factory=list)


class DiagnosticsBundleRequest(BaseModel):
    case_id: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")


class DiagnosticsUploadRequest(DiagnosticsBundleRequest):
    consent: bool = False


class RestoreExerciseRequest(BaseModel):
    backup_id: str
    encrypted: bool = False


class SecretSetRequest(BaseModel):
    name: str
    value: str


class ClientCreateRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)

    model_config = ConfigDict(extra="forbid")


class ClientStatusRequest(BaseModel):
    status: Literal["active", "archived", "quarantine"]

    model_config = ConfigDict(extra="forbid")


class ConnectorInstanceCreateRequest(BaseModel):
    connector_type: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=256)
    client_id: str | None = Field(default=None, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=256)
    config_json: str = Field(default="{}", max_length=20_000)

    model_config = ConfigDict(extra="forbid")


class ConnectorInstanceUpdateRequest(BaseModel):
    connector_type: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    client_id: str | None = Field(default=None, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=256)
    config_json: str | None = Field(default=None, max_length=20_000)
    status: Literal["inactive", "active", "error", "disabled"] | None = None

    model_config = ConfigDict(extra="forbid")


class ClientConnectorMappingCreateRequest(BaseModel):
    connector_instance_id: str = Field(min_length=1, max_length=128)
    external_company_id: str = Field(min_length=1, max_length=256)
    external_company_name: str | None = Field(default=None, max_length=256)
    client_id: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")


class ClientDiscoveryRunRequest(BaseModel):
    connector_instance_id: str | None = Field(default=None, min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")


class ClientDiscoveryBulkAcceptRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")


class DeploymentModeRequest(BaseModel):
    mode: Literal["msp", "smb"]

    model_config = ConfigDict(extra="forbid")


class QuarantineReclassificationRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")
