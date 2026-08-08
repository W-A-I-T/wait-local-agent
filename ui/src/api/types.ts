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
  params: Record<string, unknown>;
};

export type AgentDefinition = {
  id: string;
  name: string;
  trigger: "manual" | "scheduled" | "event";
  enabled: boolean;
  client_id: string | null;
  execution_window_start?: string | null;
  execution_window_end?: string | null;
  execution_window_timezone?: string;
};

export type ProviderSettings = {
  local_model_provider: string;
  local_model_base_url: string;
  local_model_name: string;
  local_model_timeout_seconds: number;
  llm_inference_enabled: boolean;
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
