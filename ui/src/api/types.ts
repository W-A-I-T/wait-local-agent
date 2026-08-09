export type ConnectorStatus = {
  id: string;
  name: string;
  status: string;
  message: string;
  kind?: string;
  write_actions_enabled?: boolean;
  http_probing_enabled?: boolean;
};

export type HaloReadResult = {
  status: string;
  message: string;
  count: number;
};

export type ConnectorHealth = {
  status: string;
  message: string;
  count?: number;
};

export type HaloTicket = {
  id: string;
  summary: string;
  status: string;
  priority: string;
  client_name: string;
  client_id?: string;
};

export type TicketSummarySource = {
  title: string;
  path: string;
  excerpt: string;
  document_id?: number | null;
  chunk_id?: number | null;
};

export type TicketSummaryResponse = {
  ticket_id: string;
  classification: string;
  summary: string;
  suggested_response: string;
  sources: TicketSummarySource[];
  approval_status?: "pending" | "approved" | "rejected";
  approval_comment?: string;
};

export type ApprovalRequest = {
  id: number;
  subject_id: string;
  action_type: string;
  status: string;
  comment: string;
  execution_status: string;
  execution_message: string;
  expires_at?: string | null;
  payload?: {
    fields?: Record<string, string | number | boolean | null>;
    [key: string]: unknown;
  };
  can_execute?: boolean;
  block_reason?: string;
  workflow_run_id?: string | number | null;
};

export type EventHistory = {
  id: number;
  event_type: string;
  subject_id: string;
  status: string;
  message: string;
};

export type EventDelivery = {
  id: number;
  idempotency_key: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  status: string;
  retry_count: number;
  max_retries: number;
  next_retry_at?: string | null;
  client_id?: string | null;
};

export type WorkflowTemplate = {
  id: string;
  name: string;
  trigger: string;
  description: string;
  action_type: string;
  approval_required: boolean;
  risk_level: string;
  preview_fields: string[];
  tool_id?: string | null;
};

export type TemplateGalleryEntry = {
  id: string;
  source_template_id: string;
  name: string;
  trigger: string;
  description: string;
  action_type: string;
  approval_required: boolean;
  risk_level: string;
  preview_fields: string[];
  provenance: string;
  instructions: string;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  client_id?: string | null;
};

export type TemplateGalleryRevision = {
  id: number;
  gallery_id: string;
  version: number;
  definition: Record<string, unknown>;
  created_at: string;
  client_id?: string | null;
};

export type TemplateGalleryRevisionDiff = {
  gallery_id: string;
  from_version: number;
  to_version: number;
  changed: boolean;
  changes: Array<{
    field: string;
    before?: unknown;
    after?: unknown;
  }>;
  client_id?: string | null;
};

export type WorkflowRun = {
  id: string | number;
  status: string;
  goal?: string;
  message?: string;
  created_at?: string;
  updated_at?: string;
  approval_request_id?: number | null;
  template_id?: string;
  ticket_id?: string;
  client_id?: string | null;
  template_version?: number | null;
};

export type WorkflowRunComparison = {
  from_run: WorkflowRun;
  to_run: WorkflowRun;
  changed: boolean;
  changes: Array<{
    field: string;
    before?: unknown;
    after?: unknown;
  }>;
};

export type AgentTool = {
  id: string;
  name: string;
  description: string;
  risk_level: string;
  required_role: string;
  approval_required: boolean;
  access_mode: string;
  approval_expiry_seconds?: number;
};

export type AgentRunDetail = {
  id: number;
  agent_id: string;
  entity_id: string;
  status: string;
  current_step: number;
  state?: {
    context?: Record<string, unknown>;
    steps?: Array<Record<string, unknown>>;
    final_result?: Record<string, unknown>;
  };
  revision_version?: number | null;
  client_id?: string | null;
};

export type AgentBackfill = {
  id: number;
  agent_id: string;
  entity_ids: string[];
  input: Record<string, unknown>;
  max_concurrency: number;
  status: string;
  next_index: number;
  processed_count: number;
  succeeded_count: number;
  failed_count: number;
  run_ids: number[];
  failed_entity_ids: string[];
  actor: string;
  error_detail: string;
  created_at: string;
  updated_at: string;
  client_id?: string | null;
};

export type AgentBackfillPreview = {
  dry_run: true;
  agent_id: string;
  entity_count: number;
  estimated_runs: number;
  max_concurrency: number;
  execution_mode: string;
  will_persist: false;
  input: Record<string, unknown>;
  client_id?: string | null;
};

export type ExecutionRun = {
  id: number;
  run_kind: string;
  source_run_id?: number | null;
  actor: string;
  status: string;
  started_at: string;
  finished_at: string;
  trigger_source: string;
  client_id?: string | null;
  metadata?: Record<string, unknown>;
};

export type ExecutionDetail = ExecutionRun & {
  steps: Array<{
    id: number;
    ordinal: number;
    kind: string;
    name: string;
    status: string;
    started_at: string;
    finished_at: string;
    input?: unknown;
    output?: unknown;
    error_detail: string;
  }>;
  artifacts: Array<{
    id: number;
    step_ordinal?: number | null;
    name: string;
    media_type: string;
    byte_size: number;
    sha256: string;
  }>;
};

export type AnalyticsSummary = {
  range: { from: string | null; to: string | null };
  client_id: string | null;
  executions_over_time: Array<{
    date: string;
    count: number;
    succeeded: number;
    not_succeeded: number;
  }>;
  success_rate: { total: number; succeeded: number; rate: number };
  failures_by_status: Array<{ status: string; count: number }>;
  activity_breakdown: Array<{
    run_kind: string;
    trigger_source: string;
    status: string;
    count: number;
  }>;
  approval_rate: {
    requested: number;
    decided: number;
    approved: number;
    rejected: number;
    pending: number;
    rate: number;
    derivation: string;
  };
  ticket_metrics: {
    touched: number;
    resolved: number;
    resolution_rate: number;
    derivation: string;
  };
  activity_by_workflow: Array<{
    run_kind: string;
    workflow_id: string;
    total: number;
    succeeded: number;
    status_counts: Array<{ status: string; count: number }>;
  }>;
  estimated_minutes_saved: {
    minutes: number;
    estimate: boolean;
    derivation: string;
  };
};

export type KnowledgeDocument = {
  id: number;
  path: string;
  title: string;
  kind: string;
  checksum: string;
  modified_at: string;
  chunk_count: number;
  indexed_at: string;
  client_id?: string | null;
};

export type KnowledgeChunk = {
  id: number;
  document_id: number;
  title: string;
  path: string;
  chunk_index: number;
  text: string;
  excerpt: string;
  client_id?: string | null;
};

export type CollectorConfigFieldOption = string | { value: string; label?: string };

export type CollectorConfigField = {
  name: string;
  label?: string;
  help?: string;
  type?: string;
  required?: boolean;
  default?: unknown;
  options?: CollectorConfigFieldOption[];
  items?: { type?: string };
};

export type CollectorModule = {
  id: string;
  name: string;
  version: string;
  description: string;
  capabilities: string[];
  scopes: string[];
  report_types: string[];
  platforms?: string[];
  config_schema?: CollectorConfigField[];
};

export type CollectorConfigPayload = {
  config: Record<string, unknown>;
  client_id?: string;
};

export type CollectorSourceOutcome = {
  source_id: string;
  status: string;
  record_count?: number;
  error_code?: string | null;
  error_detail?: string | null;
  remediation_hint?: string | null;
};

export type CollectorRunResult = {
  status?: string;
  collection_scope?: string;
  source_outcomes?: CollectorSourceOutcome[];
  metadata?: Record<string, unknown>;
};

export type CollectorRunPayload = CollectorConfigPayload & {
  confirm: boolean;
};

export type CollectorValidationResult = {
  module_id: string;
  passed: boolean;
  message: string;
  errors: string[];
};

export type CollectorPreviewResult = {
  module_id: string;
  source_name: string;
  scopes: string[];
  estimated_assets: number;
  estimated_observations: number;
  expected_reports: string[];
  metadata: Record<string, unknown>;
};

export type CollectorRun = {
  id: number;
  status: string;
  mode: string;
  source_id: number | null;
  module_id: string;
  created_at: string;
  updated_at: string;
  started_at: string;
  completed_at: string;
  message?: string | null;
  client_id?: string | null;
  actor_id?: string | null;
  result_status?: string | null;
  result_json?: string;
};

export type CollectorRunDetail = CollectorRun & {
  assets: Record<string, unknown>[];
  observations: Record<string, unknown>[];
  config_snapshots: Record<string, unknown>[];
  config_diffs: Record<string, unknown>[];
  restore_exercises: Record<string, unknown>[];
};

export type ReportSummary = {
  id: string;
  report_type: string;
  project_id: string | null;
  created_at: string;
  updated_at: string;
  status: string;
  subject: string;
  client_id?: string | null;
};

export type ReportExport = {
  report_type: string;
  subject: string;
  metadata: Record<string, unknown>;
  sections: Record<string, unknown>[];
};

export type EvidenceStatus = "not_run" | "no_evidence" | "partial" | "completed";

export type HardeningCheckResult = {
  id: number | null;
  run_id: number;
  check_id: string;
  title: string;
  scope: string;
  severity: string;
  status: string;
  evidence: Record<string, unknown>;
  remediation_hint: string | null;
};

export type HardeningRun = {
  id: number | null;
  status: string;
  started_at: string;
  completed_at: string;
  expected_check_count: number;
  result_count: number;
  results: HardeningCheckResult[];
};

export type RestoreExercise = {
  id: number | null;
  exercise_id: string;
  status: string;
  target: string;
  backup_artifact_id: string;
  validation_json: string;
  evidence_json: string;
  started_at: string;
  completed_at: string;
};

export type EvidenceReport = ReportSummary & {
  title?: string;
  evidence_status?: EvidenceStatus;
  metadata?: Record<string, unknown>;
  sections?: Record<string, unknown>[];
};

export type AuditEvent = {
  id: number;
  event_type: string;
  subject_id: string;
  status: string;
  message: string;
  detail?: string;
  created_at?: string;
  client_id?: string | null;
};

export type AuditExportResponse = {
  count: number;
  events: AuditEvent[];
};

export type ScheduledJob = {
  id: number;
  job_kind: "workflow" | "agent";
  template_id: string | null;
  agent_id: string | null;
  entity_id: string | null;
  cron: string;
  schedule_type: "cron" | "interval" | "once";
  interval_seconds?: number | null;
  run_at?: string | null;
  timezone: string;
  paused: boolean;
  created_at: string;
  updated_at: string;
  client_id: string | null;
  next_run_at: string | null;
  params?: Record<string, unknown> | null;
};

export type ScheduledJobRequestBody = {
  template_id?: string;
  agent_id?: string;
  entity_id?: string;
  cron: string;
  schedule_type?: "cron" | "interval" | "once";
  interval_seconds?: number;
  run_at?: string;
  timezone?: string;
  params: Record<string, unknown>;
};

export type AgentDefinition = {
  id: string;
  name: string;
  description: string;
  trigger: "manual" | "scheduled" | "event";
  enabled: boolean;
  entity_type: string;
  filters: Record<string, unknown>;
  enabled_tools: string[];
  steps: Array<{ tool_id: string; payload: Record<string, unknown> }>;
  max_steps: number;
  execution_timeout_seconds: number;
  client_id: string | null;
  version: number;
  run_once_per_entity: boolean;
  depends_on_agent_ids: string[];
  execution_window_start?: string | null;
  execution_window_end?: string | null;
  execution_window_timezone?: string;
  context_sources: string[];
  approval_expiry_seconds?: number | null;
};

export type AgentPlan = {
  instruction: string;
  entity_id: string;
  client_id: string | null;
  status: "preview" | "blocked";
  steps: Array<{
    index: number;
    tool_id: string;
    name: string;
    reason: string;
    risk_level: string;
    required_role: string;
    approval_required: boolean;
    access_mode: string;
    payload: Record<string, unknown>;
  }>;
  context: Record<string, unknown>;
  definition: Record<string, unknown>;
  blocked_reason: string;
};

export type ProviderSettings = {
  local_model_provider: string;
  local_model_base_url: string;
  local_model_name: string;
  local_model_timeout_seconds: number;
  llm_inference_enabled: boolean;
  cloud_fallback_enabled?: boolean;
  remote_model_provider?: string;
  remote_model_configured?: boolean;
  vector_backend: string;
  document_parser: string;
  ocr_enabled: boolean;
  embedding_provider: string;
  embedding_model: string;
  qdrant_collection: string;
};

export type SecuritySettings = {
  api_token_configured: boolean;
  admin_token_configured: boolean;
  tech_token_configured: boolean;
  viewer_token_configured: boolean;
  api_auth_required: boolean;
  demo_mode: boolean;
};

export type PackInfo = {
  name: string;
  version: string;
  locked: boolean;
  requires_license: boolean;
};

export type SecretRecord = {
  key: string;
  configured: boolean;
  required_for: string;
};

export type UpdateStatus = {
  status: string;
  detail: string;
  version?: string | null;
  update_available?: boolean | null;
  target_version?: string | null;
};

export type HaloTicketsResponse = {
  result: HaloReadResult;
  items: HaloTicket[];
};

export type AuthRoleResponse = {
  role: "admin" | "technician" | "viewer";
  api_auth_required: boolean;
  demo_mode: boolean;
};

export type FounderUploadPreview = {
  artifact_id: string;
  project_id?: string;
  schemaVersion?: string;
  sourceCode?: boolean;
  file_count?: number;
  dependency_count?: number;
  env_key_names?: string[];
  finding_count?: number;
};

export type LaunchPassportStatus = {
  status: "connected" | "unreachable" | "not_authorized" | "unknown";
  lp_project_id?: string;
  token_configured: boolean;
  capabilities?: {
    launch_scan?: boolean;
  };
};

export type FounderScanState = "queued" | "pending" | "pending_upload" | "running" | "completed" | "uploaded" | "failed" | "cancelled" | "unknown";

export type FounderScanView = {
  artifact_id: string;
  status: FounderScanState;
};

export type FounderResults = {
  project_id?: string;
  scans: {
    count: number;
    states: FounderScanState[];
  };
  latest_report: {
    available: boolean;
  };
};
