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

export type CollectorModule = {
  id: string;
  name: string;
  version: string;
  description: string;
  capabilities: string[];
  scopes: string[];
  report_types: string[];
};

export type CollectorConfigPayload = {
  config: Record<string, string | number | boolean | null>;
  client_id?: string;
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
  template_id: string;
  cron: string;
  paused: boolean;
  created_at: string;
  updated_at: string;
  client_id: string | null;
  next_run_at: string | null;
  params?: Record<string, unknown> | null;
};

export type ScheduledJobRequestBody = {
  template_id: string;
  cron: string;
  params: Record<string, string | number | boolean | null>;
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
