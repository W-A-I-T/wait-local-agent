export type ConnectorStatus = {
  id: string;
  name: string;
  status: string;
  message: string;
  kind?: string;
  write_actions_enabled?: boolean;
  http_probing_enabled?: boolean;
};

export type ReadinessStep = {
  id: string;
  label: string;
  status: "done" | "todo" | "info";
  required: boolean;
  detail?: string;
};

export type ConnectorInstance = {
  connector_instance_id: string;
  connector_type: string;
  display_name: string;
  client_id: string | null;
  credential_ref: string | null;
  config_json: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type PollSummary = {
  connector_instance_id: string;
  pages_fetched: number;
  written: number;
  quarantined: number;
  status: "idle" | "degraded" | "failed" | "skipped_locked";
  reason: string | null;
};

export type Client = {
  client_id: string;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ClientDirectoryEntry = Pick<Client, "client_id" | "name" | "status">;

export type CommercialActivation = {
  client_id: string;
  activated_at: string;
  activated_by: string;
};

export type EntitlementResponse = {
  commercial: Record<string, unknown> | null;
};

export type DeploymentMode = "msp" | "smb";

export type ClientCandidate = {
  candidate_id: string;
  connector_instance_id: string;
  provider: string;
  external_id: string;
  display_name: string;
  domains_json: string;
  provenance: string;
  first_seen: string;
  last_seen: string;
  match_state: "verified" | "proposed" | "ambiguous" | "unmatched" | "conflicting" | "dismissed";
  matched_client_id: string | null;
  match_reason: string;
  confidence: number;
};

export type DiscoveryResponse = {
  items: ClientCandidate[];
  page: number;
  page_size: number;
  summary: {
    discovered: number;
    reconciled: number;
    need_confirmation: number;
    unmatched: number;
    conflicts: number;
  };
};

export type AutomationDiscoveryStatus = {
  status: string;
  external_writes: boolean;
  discovery_source: string;
  measured_labor_source: string;
};

export type AutomationDiscoveryCategory = {
  category_id: string;
  label: string;
  patterns: string[];
  workflows: string[];
  playbooks: string[];
  prerequisites: string[];
  default_minutes_estimate: number;
};

export type AutomationMappingReadiness = {
  client_id?: string;
  families: Record<string, { verified: number; unverified: number }>;
  mappings: Array<{
    mapping_id: string;
    connector_instance_id: string;
    connector_type: string;
    family: string;
    external_company_id: string;
    external_company_name: string;
    verified: boolean;
  }>;
  verified_count: number;
  unverified_count: number;
  coverage_goal: string[];
};

export type AutomationTimeEntryImportResponse = {
  client_id: string;
  inserted: number;
  duplicate: number;
  rejected: number;
  external_writes: boolean;
};

export type EntityRef = {
  id: number;
  client_id: string;
  entity_type: string;
  source_system: string;
  external_id: string;
  display_name: string;
  provenance: string;
  attributes_json?: string;
  first_seen?: string;
  last_seen?: string;
};

export type EntityLink = {
  id: number;
  client_id: string;
  from_ref_id: number;
  to_ref_id: number;
  link_type: string;
  provenance: string;
};

export type ClientGraph = {
  refs: EntityRef[];
  links: EntityLink[];
  total_refs: number;
  total_links: number;
  has_more: boolean;
  entity_type_counts?: Record<string, number>;
};

export type ClientBaseline = {
  baseline_id: string;
  client_id: string;
  version: number;
  generated_at: string;
  accepted: boolean;
  source_coverage: Record<string, string>;
  summary: Record<string, unknown>;
  sections: Record<string, unknown>;
};

export type BaselineFinding = {
  domain: string;
  path: string;
  classification: string;
  previous: unknown;
  current: unknown;
  correlation?: string;
  approval_id?: number;
  correlation_label?: string;
};

export type ClientDrift = {
  client_id: string;
  baseline_version: number;
  baseline_generated_at: string;
  generated_at: string;
  unchanged: boolean;
  findings: BaselineFinding[];
  source_coverage: Record<string, string>;
  fresh_summary: Record<string, unknown>;
};

export type RmmInventorySyncResult = {
  devices: number;
  alerts: number;
  links: number;
  errors: string[];
};

export type M365InventorySyncResult = {
  users: number;
  devices: number;
  links: number;
  errors: string[];
};

export type SyncCursor = {
  connector_instance_id: string;
  cursor_type: string;
  cursor_value: string | null;
  status: "idle" | "syncing" | "degraded" | "failed";
  last_synced_at: string | null;
  updated_at: string;
};

export type UnmappedRecord = {
  record_id: string;
  connector_instance_id: string;
  external_company_id: string | null;
  external_id: string | null;
  record_type: string;
  payload_digest: string | null;
  reason: string;
  created_at: string;
  resolved_at: string | null;
};

export type ClientConnectorMapping = {
  mapping_id: string;
  connector_instance_id: string;
  external_company_id: string;
  external_company_name: string | null;
  client_id: string;
  verified: number;
  created_at: string;
  updated_at: string;
};

export type MappingVerifyResult = ClientConnectorMapping & {
  retenanted_count: number;
};

export type QuarantinedTicket = {
  id: string;
  client: string;
  subject: string;
  body: string;
  priority: string;
  status: string;
  client_id: string | null;
  requester_id: string | null;
  created_at: string;
  updated_at: string;
  source_system: string | null;
  connector_instance_id: string | null;
  external_id: string | null;
  external_client_id: string | null;
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

export type Ticket = {
  id: string;
  client_id?: string | null;
  summary?: string | null;
  subject?: string | null;
  status?: string | null;
  priority?: string | null;
  source_system?: string | null;
  external_id?: string | null;
  requester_id?: string | null;
};

export type TicketNote = {
  id: number | string;
  ticket_id: string;
  author?: string | null;
  body: string;
  created_at?: string | null;
};

export type TicketStatusHistory = {
  id?: number | string;
  ticket_id?: string;
  from_status?: string | null;
  to_status?: string | null;
  from?: string | null;
  to?: string | null;
  status?: string | null;
  actor?: string | null;
  changed_by?: string | null;
  created_at?: string | null;
  at?: string | null;
};

export type TicketContext = {
  schemaVersion?: string | number;
  first_scan?: unknown;
  modules?: unknown[];
  refs?: Array<Record<string, unknown>>;
  links?: Array<Record<string, unknown>>;
};

export type EndUserTicket = {
  ticket_id: string;
  subject: string;
  body: string;
  status: string;
  priority: string;
};

export type EndUserBranding = {
  brand_name: string;
  brand_tagline: string;
  brand_logo_data_uri: string;
  brand_accent_color: string;
  brand_surface_color: string;
};

export type EndUserMessage = {
  id: number;
  ticket_id: string;
  role: "requester" | "support";
  body: string;
  created_at: string;
};

export type TechnicianChatMessage = {
  id: number;
  role: "user" | "assistant";
  message: string;
  action_id?: string | null;
  status: string;
  ticket_id?: string | null;
  created_at: string;
};

export type TechnicianChatSession = {
  id: string;
  status: "active" | "closed";
  ticket_id?: string | null;
  client_id: string;
  created_at: string;
  updated_at: string;
  messages: TechnicianChatMessage[];
};

export type TechnicianChatResponse = {
  status: string;
  message: string;
  action_id?: string;
  session_id?: string;
  plan?: {
    status: string;
    blocked_reason?: string;
    steps: Array<{
      index: number;
      tool_id: string;
      name: string;
      reason: string;
      risk_level: string;
      required_role: string;
      approval_required: boolean;
      access_mode: string;
    }>;
    definition?: Record<string, unknown>;
  };
  result?: {
    status: string;
    output?: Record<string, unknown>;
    error_detail?: string;
  };
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
  output?: Record<string, unknown>;
  workflow_run_id?: string | number | null;
};

export type EventHistory = {
  id: number;
  event_type: string;
  subject_id: string;
  status: string;
  message: string;
  payload_json: string;
  created_at: string;
  client_id?: string | null;
};

export type EventDelivery = {
  id: number;
  idempotency_key: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  payload?: Record<string, unknown>;
  status: string;
  error_detail?: string;
  matched_agent_count?: number;
  agent_ids?: unknown[];
  run_ids?: unknown[];
  matched_playbook_count?: number;
  playbook_ids?: unknown[];
  playbook_run_ids?: unknown[];
  playbook_attempts?: Record<string, unknown>;
  agent_attempts?: Record<string, unknown>;
  retry_count: number;
  max_retries: number;
  retry_delay_seconds: number;
  next_retry_at?: string | null;
  received_at: string;
  processed_at: string;
  client_id?: string | null;
};

export type EventDispatchResult = {
  delivery: EventDelivery;
  duplicate: boolean;
  matched_agent_ids: string[];
  run_ids: number[];
  matched_playbook_ids: string[];
  playbook_run_ids: string[];
  errors: string[];
};

export type SmartActionRun = {
  id: number;
  action_id: string;
  actor: string;
  status: string;
  approval_id?: number | null;
  output?: Record<string, unknown>;
  evidence?: Array<Record<string, unknown>>;
  error_detail?: string;
  created_at: string;
  updated_at: string;
  client_id?: string | null;
};

export type SmartActionManifest = {
  action_id: string;
  title: string;
  description: string;
  kind: "deterministic" | "ai_assisted" | string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  requires_approval: boolean;
  estimated_minutes_saved: number;
  risk_level: string;
  required_role: string;
  access_mode: string;
  approval_expiry_seconds: number;
};

export type SmartActionInvokeResult = {
  status: string;
  approval_id?: number | null;
  output?: Record<string, unknown>;
  evidence?: Array<Record<string, unknown>>;
  error_detail?: string;
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
  payload_schema?: {
    type?: string;
    required?: string[];
    properties?: Record<string, string>;
  };
};

export type MspPlaybookStep = {
  id: string;
  name: string;
  kind: "workflow" | "report" | string;
  description: string;
  workflow_template_id?: string | null;
  report_type?: string | null;
  required_inputs: string[];
};

export type MspPlaybook = {
  id: string;
  name: string;
  version: number;
  trigger: string;
  description: string;
  risk_level: string;
  steps: MspPlaybookStep[];
  output_evidence: string[];
  local_fixture?: boolean;
};

export type MspPlaybookEntry = {
  id: string;
  source_playbook_id: string;
  definition: MspPlaybook;
  provenance: string;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  client_id?: string | null;
};

export type MspPlaybookRevision = {
  id: number;
  playbook_id: string;
  version: number;
  snapshot: {
    definition?: MspPlaybook;
    provenance?: string;
    enabled?: boolean;
  };
  created_at: string;
  client_id?: string | null;
};

export type MspPlaybookRevisionDiff = {
  playbook_id: string;
  from_version: number;
  to_version: number;
  changed_fields: string[];
  from: Record<string, unknown>;
  to: Record<string, unknown>;
};

export type MspPlaybookSubscription = {
  id: string;
  playbook_id: string;
  event_type: string;
  client_id: string;
  input_mapping: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type ConsultantBlueprint = {
  id: string;
  client_id: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  solution: { name: string };
  risk: string;
  agents: Array<{ id: string; name: string; purpose: string; tools: string[]; knowledge: string[] }>;
  workflows: Array<{ id: string; name: string; trigger: string; steps: string[] }>;
};

export type ConsultantArchitectureComponent = {
  id: string;
  kind: string;
  name?: string;
  status: string;
  implementation?: string;
  trigger?: string;
  steps?: string[];
  resolved_tool_ids?: string[];
  unresolved_tool_ids?: string[];
  requested_tool_ids?: string[];
  knowledge_references?: string[];
};

export type ArchitectureDecision = {
  id: string;
  capability: string;
  component_id: string;
  chosen_target: string;
  why: string;
  status: string;
  alternatives_considered?: string[];
  dependencies?: string[];
  required_permissions?: string[];
  licenses?: string[];
  read_write_behavior?: string | string[];
  approval_requirements?: string | string[];
  risk?: string;
  reversibility?: string;
  execution_boundary?: string;
  estimated_complexity?: string;
  data_movement?: string;
  systems_involved?: string[];
  testing_requirements?: string[];
  deployment_requirements?: string[];
  open_questions?: string[];
  evidence?: string[];
  evidence_quality?: string;
};

export type ConsultantArchitecture = {
  blueprint_id: string;
  client_id: string;
  solution: { name: string };
  risk: string;
  approval_policy: Record<string, string>;
  components: ConsultantArchitectureComponent[];
  open_items: Array<{ kind: string; component_id: string; detail: string }>;
  readiness: "ready" | "needs_review";
  execution_started: boolean;
  deployment_started: boolean;
  decisions?: ArchitectureDecision[];
  decision_engine?: {
    format?: string;
    authority?: string;
    decision_count?: number;
    unresolved_decision_count?: number;
    inference_started?: boolean;
    execution_started?: boolean;
    deployment_started?: boolean;
  };
  supervisor?: {
    mode: string;
    children: Array<{ id: string; kind: string; purpose?: string; context_policy?: string }>;
    context_policy?: string;
    execution_started?: boolean;
  };
};

export type ConsultantEnvironmentSystem = {
  id: string;
  name: string;
  kind: string;
  connector_id?: string | null;
  status: string;
  evidence: string[];
  limitation?: string | null;
  tenant_scope: string;
  provider_status?: string;
  http_probing_enabled?: boolean;
  write_actions_enabled?: boolean;
  probe?: {
    status: string;
    layer: string;
    message?: string;
  };
};

export type ConsultantEnvironmentResult = {
  format: string;
  format_version: number;
  client_id: string;
  source: string;
  probe_requested: boolean;
  probe_performed: boolean;
  systems: ConsultantEnvironmentSystem[];
  unresolved: Array<{ system: string; reason: string }>;
  limitations: Array<{ system: string; reason: string }>;
  readiness: string;
  inference_started: boolean;
  execution_started: boolean;
  deployment_started: boolean;
};

export type ConsultantGovernanceResult = {
  client_id: string;
  status: string;
  finding_counts: { high: number; medium: number; info: number };
  findings: Array<{ severity: string; code: string; message: string; component_id?: string }>;
  connectors: Array<{
    connector_id: string;
    host?: string | null;
    action_count: number;
    write_action_ids: string[];
    authentication_types: unknown[];
    review_status: string;
  }>;
  policy_mapping: Array<{ policy_id: string; status: string; evidence: string }>;
  authorization_changed: boolean;
  execution_started: boolean;
  deployment_started: boolean;
};

export type ConsultantEvaluationResult = {
  case_count: number;
  dimensions: Record<string, number>;
  production_readiness: string;
  execution_started: boolean;
  execution_mode: "observation" | "controlled" | string;
  cases: Array<{
    id: string;
    checks: Record<string, boolean>;
    passed: boolean;
    execution?: Record<string, unknown>;
  }>;
  executed_case_count?: number;
  execution_errors?: Array<{ case_id: string; error: string }>;
};

export type ConsultantDeliveryPlan = {
  format: string;
  format_version: number;
  client_id: string;
  summary: Record<string, number | string | boolean>;
  checks: Record<string, boolean>;
  production_readiness: string;
  deployment_targets: string[];
  review_package?: Record<string, unknown> | null;
  review_package_generated: boolean;
  review_package_digest?: string | null;
  delivery_bundle?: ConsultantDeliveryBundle | null;
  delivery_bundle_generated: boolean;
  delivery_bundle_digest?: string | null;
  delivery_bundle_status: string;
  deployable_source_package?: Record<string, unknown> | null;
  deployable_source_package_generated: boolean;
  deployable_source_package_digest?: string | null;
  deployment_package_generated: boolean;
  deployment_package_status: string;
  production_deployment_requires_approval: boolean;
  execution_started: boolean;
  deployment_started: boolean;
  authorization_changed: boolean;
};

export type ConsultantUseCase = {
  id: string;
  title: string;
  category: string;
  business_goal: string;
  services: string[];
  agent_roles: string[];
  outputs: string[];
  approval_boundaries: string[];
};

export type ConsultantUseCaseCatalog = {
  format: string;
  format_version: number;
  category: string | null;
  execution_started: boolean;
  deployment_started: boolean;
  use_cases: ConsultantUseCase[];
};

export type ConsultantMonitoring = {
  client_id: string;
  agent_count: number;
  total_runs: number;
  failed_runs: number;
  failure_rate: number | null;
  payloads_exposed: boolean;
};

export type ConsultantDeliveryBundle = {
  manifest: {
    format: string;
    format_version: number;
    client_id: string;
    bundle_status: string;
    deployable: boolean;
    credentials_included: boolean;
    execution_started: boolean;
    deployment_started: boolean;
    deployment_targets: string[];
    source_review_package_digest: string;
    files: Array<{ path: string; media_type: string; digest: string }>;
    open_items: string[];
  };
  files: Array<{ path: string; media_type: string; digest: string; content: unknown }>;
};

export type ConsultantEmployeeOnboardingDemo = {
  format: string;
  format_version: number;
  client_id: string;
  entity_id: string;
  mode: "local_fixture" | string;
  stages: {
    blueprint: { id: string; solution_name: string; risk: string };
    supervisor: { status: string; children?: Array<{ status?: string }> };
    evaluation: { production_readiness: string; execution_started: boolean };
    governance: { status: string };
    artifacts: {
      status: string;
      items: Array<Record<string, unknown>>;
      package_digest: string;
      delivery_bundle?: ConsultantDeliveryBundle;
      delivery_bundle_digest?: string;
      delivery_bundle_status?: string;
      deployment_package_generated: boolean;
    };
    delivery: {
      production_readiness: string;
      deployment_started: boolean;
      delivery_bundle?: ConsultantDeliveryBundle;
      delivery_bundle_digest?: string;
      delivery_bundle_status?: string;
    };
  };
  boundaries: {
    live_provider_execution: boolean;
    artifact_generation: boolean;
    artifact_generation_status: string;
    review_package_generated: boolean;
    delivery_bundle_generated?: boolean;
    delivery_bundle_status?: string;
    deployable_package_generated: boolean;
    deployment_started: boolean;
    production_deployment_requires_approval: boolean;
    external_systems_require_environment_verification: boolean;
    sensitive_operations_require_human_approval: boolean;
  };
  audit: { audit_event_count: number; agent_run_count: number };
};

export type PowerAutomateFlowPlan = {
  format: string;
  format_version: number;
  client_id: string;
  workflow_id: string;
  workflow_name: string;
  power_automate: {
    trigger: { type: string; name: string };
    actions: Array<{
      id: string;
      name: string;
      kind: string;
      type: string;
      tool_id?: string | null;
      method: string;
      approval_required: boolean;
    }>;
  };
  requires_approval: boolean;
  credentials_included: boolean;
  execution_started: boolean;
  deployment_started: boolean;
  export_status: string;
};

export type PowerAppsArtifact = {
  format: string;
  format_version: number;
  client_id: string;
  app_name: string;
  solution: { unique_name: string; publisher_prefix: string };
  dataverse: { tables: Array<Record<string, unknown>> };
  canvas_app: { screens: Array<Record<string, unknown>>; connector_references: Array<Record<string, unknown>> };
  files: Array<{ path: string; media_type: string; content: unknown }>;
  requires_approval: boolean;
  credentials_included: boolean;
  build_started: boolean;
  dataverse_write_started: boolean;
  execution_started: boolean;
  deployment_started: boolean;
  package_status: string;
};

export type ConsultantDiscoveryResult = {
  format: string;
  format_version: number;
  client_id: string;
  missing_required: string[];
  readiness: string;
  risk_review: { level: string; factors: string[]; evidence_only: boolean };
  roi_analysis: {
    status: string;
    estimated_monthly_hours_saved?: number;
    estimated_monthly_value?: number;
    evidence_only?: boolean;
  };
  blueprint_candidate: Record<string, unknown>;
  answered?: Record<string, unknown>;
  unanswered?: string[];
  questions?: ConsultantDiscoveryQuestion[];
  next_question?: ConsultantDiscoveryQuestion | null;
  assistant_message?: string;
  status?: string;
  inference_started: boolean;
  execution_started: boolean;
  deployment_started: boolean;
};

export type ConsultantBlueprintPromotionResult = {
  blueprint: ConsultantBlueprint;
  discovery: ConsultantDiscoveryResult;
  execution_started: boolean;
  deployment_started: boolean;
};

export type ConsultantDiscoveryQuestion = {
  id: string;
  prompt: string;
  kind: "text" | "list" | "boolean";
  required: boolean;
  answered: boolean;
};

export type ConsultantDiscoverySession = ConsultantDiscoveryResult & {
  session_id: string;
  principal_scope: string;
  transcript: Array<{ role: "user" | "assistant"; field?: string; content: unknown }>;
  turn_index: number;
  next_question: ConsultantDiscoveryQuestion | null;
  blueprint_id?: string | null;
  session_status?: "active" | "completed";
  created_at?: string;
  updated_at?: string;
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
  definition?: WorkflowDesign;
};

export type WorkflowNodeType = "trigger" | "action" | "approval" | "condition" | "knowledge" | "connector" | "notification" | "end";

export type WorkflowDesignNode = {
  id: string;
  type: WorkflowNodeType;
  label: string;
  tool_id?: string | null;
  config: Record<string, unknown>;
};

export type WorkflowDesignEdge = {
  from: string;
  to: string;
};

export type WorkflowDesign = {
  format: "wait-local-agent.workflow-design";
  version: 1;
  nodes: WorkflowDesignNode[];
  edges: WorkflowDesignEdge[];
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
  title?: string;
  description: string;
  risk_level: string;
  required_role: string;
  approval_required: boolean;
  access_mode: string;
  approval_expiry_seconds?: number;
};

export type AgentFailurePolicy = {
  mode: "stop" | "retry" | "fallback" | "human_input" | "technician_escalation" | "blocked";
  max_retries?: number;
  fallback_tool_id?: string | null;
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
  lineage?: {
    retry_count: number;
    retry_of_run_id?: number | null;
    partial_history?: {
      attempted_steps?: number;
      completed_steps?: number;
      failed_steps?: number;
      partial?: boolean;
    };
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
    historical_resolution: {
      resolved_with_history: number;
      with_duration: number;
      average_minutes: number | null;
      derivation: string;
    };
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
  model_usage: {
    runs_with_usage: number;
    runs_with_cost: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
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
  authority: string;
  sop_version?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  superseded_by?: number | null;
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

export type ApplianceHealth = {
  status: string;
  write_actions_enabled: boolean;
  http_probing_enabled: boolean;
  cloud_fallback_enabled: boolean;
  offline_mode: boolean;
  llm_inference_enabled: boolean;
  api_auth_required: boolean;
  demo_mode: boolean;
  secrets_backend: string;
  scheduler_enabled: boolean;
  halopsa_configured: boolean;
  hudu_configured: boolean;
  syncro_configured: boolean;
  servicenow_configured: boolean;
  autotask_configured: boolean;
  itglue_configured: boolean;
  confluence_configured: boolean;
  sharepoint_configured: boolean;
  m365_configured: boolean;
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
  job_kind: "workflow" | "playbook" | "agent" | "report" | "connector_poll" | "graph_sync" | "baseline_snapshot" | "backup";
  template_id: string | null;
  playbook_id: string | null;
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
  last_run?: string | null;
};

export type ScheduledJobRequestBody = {
  template_id?: string;
  playbook_id?: string;
  report_type?: "qbr" | "automation_opportunity" | "recurring_service_review";
  agent_id?: string;
  entity_id?: string;
  job_kind?: "graph_sync" | "backup";
  graph_sync?: boolean;
  cron: string;
  schedule_type?: "cron" | "interval" | "once";
  interval_seconds?: number;
  run_at?: string;
  timezone?: string;
  params: Record<string, unknown>;
};

export type BackupRun = {
  backup_run_id: number;
  started_at: string;
  finished_at: string;
  status: "succeeded" | "failed";
  destination: string;
  size_bytes: number | null;
  failure_summary: string;
};

export type BackupStatusResponse = {
  items: BackupRun[];
  page: number;
  page_size: number;
  total: number;
  schedule_configured: boolean;
  schedule: ScheduledJob | null;
  last_restore_exercise: {
    id: number | null;
    exercise_id: string;
    status: string;
    backup_artifact_id: string;
    completed_at: string;
    evidence_reference: string;
  } | null;
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
  steps: Array<{ tool_id: string; payload: Record<string, unknown>; failure_policy?: AgentFailurePolicy }>;
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
  result_aware: boolean;
  approval_required_tools: string[];
  approval_rules: AgentApprovalRule[];
};

export type AgentApprovalRule = {
  tool_id: string;
  when: {
    priority?: string[];
    status?: string[];
    actor_role?: string[];
  };
};

export type AgentRevision = {
  id: number | null;
  agent_id: string;
  version: number;
  definition: Record<string, unknown>;
  created_at: string;
  client_id?: string | null;
};

export type AgentRevisionDiff = {
  agent_id: string;
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
  selection_mode?: "deterministic" | "model";
};

export type ProviderSettings = {
  local_model_provider: string;
  local_model_base_url: string;
  local_model_name: string;
  local_model_timeout_seconds: number;
  provider_scope?: "appliance-wide";
  context_scope?: "tenant-scoped";
  llm_inference_enabled: boolean;
  cloud_fallback_enabled?: boolean;
  offline_mode?: boolean;
  remote_model_enabled?: boolean;
  remote_model_provider?: string;
  remote_model_configured?: boolean;
  model_input_cost_usd_per_million_tokens?: number;
  model_output_cost_usd_per_million_tokens?: number;
  vector_backend: string;
  document_parser: string;
  ocr_enabled: boolean;
  embedding_provider: string;
  embedding_model: string;
  qdrant_collection: string;
};

export type ProviderHealth = {
  local: {
    provider: string | null;
    model: string | null;
    scope?: "appliance-wide";
    status: string;
    probe: string;
    detail?: string;
    model_available?: boolean | null;
  };
  remote: {
    provider: string | null;
    model: string | null;
    scope?: "appliance-wide";
    status: string;
    probe: string;
    model_available?: boolean | null;
  };
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
  signature_status?: "not_recorded";
};

export type PackStatus = PackInfo & {
  cli_available: boolean;
  router_available: boolean;
  mounted_cli: boolean;
  mounted_router: boolean;
  error: string | null;
  signature_status: "not_recorded";
};

export type DiagnosticSectionError = {
  status: "degraded";
  section: string;
};

export type DiagnosticsSummary = {
  system: {
    version: string;
    build_commit: string | null;
    update_channel_configured: boolean;
    os_name: string;
    install_mode: string;
    surface_mode: string;
    free_disk_bytes: number;
    process_started_at: string;
    uptime_seconds: number;
  } | DiagnosticSectionError;
  configuration: ({
    write_actions_enabled: boolean;
    http_probing_enabled: boolean;
    cloud_fallback_enabled: boolean;
    offline_mode: boolean;
    llm_inference_enabled: boolean;
    api_auth_required: boolean;
    demo_mode: boolean;
    scheduler_enabled: boolean;
    secrets_backend: string;
    paths: Record<string, { exists: boolean; writable: boolean }>;
  } & Record<string, boolean | string | Record<string, { exists: boolean; writable: boolean }>>) | DiagnosticSectionError;
  database: { schema_version: number | null; integrity_check: string } | DiagnosticSectionError;
  connectors: Array<{ id: string; readiness: string }> | DiagnosticSectionError;
  packs: Array<{ id: string; version: string; signature_status: string }> | DiagnosticSectionError;
  failed_executions: Array<{
    run_kind: string;
    status: string;
    started_at: string;
    finished_at: string;
    trigger_source: string;
    steps: Array<{ kind: string; name: string; status: string; error: string }>;
  }> | DiagnosticSectionError;
  audit_events: Array<{ type: string; status: string }> | DiagnosticSectionError;
  hardening: { status: string; expected_check_count?: number; result_count?: number } | DiagnosticSectionError;
  update_status: { status: string; detail: string; configured: boolean } | DiagnosticSectionError;
  correlation_ids: string[] | DiagnosticSectionError;
  support_upload: { configured: boolean; available: boolean };
};

export type SupportBundlePreview = {
  inclusions: string[];
  exclusions: string[];
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

export type MicrosoftAdminReadResult = {
  status: string;
  message: string;
  count: number;
};

export type MicrosoftAdminEvidencePage<T> = {
  result: MicrosoftAdminReadResult;
  items: T[];
  next_cursor: string;
};

export type MicrosoftAdminServiceHealth = {
  id: string;
  service: string;
  status: string;
};

export type MicrosoftAdminServiceIssue = {
  id: string;
  title: string;
  service: string;
  status: string;
  classification: string;
  origin: string;
  impact_description: string;
  start_date_time: string;
  end_date_time: string;
  last_modified_date_time: string;
  feature: string;
  feature_group: string;
};

export type MicrosoftAdminSecureScore = {
  id: string;
  created_date_time: string;
  current_score: number | null;
  max_score: number | null;
  enabled_services: string[];
  licensed_user_count: number | null;
  active_user_count: number | null;
  average_comparative_scores: Array<{ basis: string; average_score: number | null }>;
};

export type MicrosoftAdminSignIn = {
  id: string;
  user_display_name: string;
  user_principal_name: string;
  created_date_time: string;
  application: string;
  conditional_access_status: string;
  risk_level: string;
  risk_state: string;
  error_code: number;
  failure_reason: string;
  additional_details: string;
  device: {
    display_name: string;
    operating_system: string;
    browser: string;
    is_compliant: boolean | null;
    is_managed: boolean | null;
    trust_type: string;
  };
  location: {
    city: string;
    state: string;
    country_or_region: string;
  };
};

export type MicrosoftAdminConditionalAccessPolicy = {
  id: string;
  display_name: string;
  state: string;
  created_date_time: string;
  modified_date_time: string;
  conditions: {
    included_users: number;
    included_groups: number;
    included_applications: number;
    included_platforms: string[];
    client_app_types: string[];
  };
  grant_controls: { operator: string; built_in_controls: string[] };
  session_control_names: string[];
};

export type MicrosoftAdminRiskyUser = {
  id: string;
  user_display_name: string;
  user_principal_name: string;
  risk_detail: string;
  risk_level: string;
  risk_state: string;
  risk_last_updated_date_time: string;
  is_deleted: boolean | null;
  is_processing: boolean | null;
};

export type MicrosoftAdminIntuneApp = {
  id: string;
  display_name: string;
  publisher: string;
  created_date_time: string;
  last_modified_date_time: string;
  is_featured: boolean | null;
  owner: string;
  developer: string;
};

export type MicrosoftAdminCompliancePolicy = {
  id: string;
  display_name: string;
  description: string;
  created_date_time: string;
  last_modified_date_time: string;
  version: number | null;
};

export type MicrosoftAdminAutopilotDevice = {
  id: string;
  display_name: string;
  group_tag: string;
  manufacturer: string;
  model: string;
  enrollment_state: string;
  last_contacted_date_time: string;
  azure_ad_device_id: string;
  managed_device_id: string;
};

export type MicrosoftAdminSecurityIncident = {
  id: string;
  display_name: string;
  status: string;
  severity: string;
  classification: string;
  determination: string;
  assigned_to: string;
  created_date_time: string;
  last_update_date_time: string;
  redirect_incident_id: string;
  custom_tags: string[];
};

export type MicrosoftAdminSecurityAlert = {
  id: string;
  title: string;
  status: string;
  severity: string;
  category: string;
  service_source: string;
  detection_source: string;
  created_date_time: string;
  last_update_date_time: string;
  incident_id: string;
};

export type MicrosoftAdminRemediation = {
  action_id: string;
  risk_level: number;
  approval_required: boolean;
  description: string;
};

export type MicrosoftAdminRunbookPlan = {
  format: string;
  runbook_id: string;
  runbook_version: string;
  title: string;
  client_id: string;
  effect: "read" | "write";
  risk_level: number;
  approval_required: boolean;
  parameters: Record<string, boolean | number | string>;
  script_sha256: string;
  timeout_seconds: number;
  credentials_included: boolean;
  plan_digest: string;
};

export type AuthRoleResponse = {
  role: "admin" | "technician" | "viewer";
  client_id?: string | null;
  client_ids?: string[];
  api_auth_required: boolean;
  demo_mode: boolean;
  end_user_support_enabled: boolean;
  is_msp_admin?: boolean;
  principal_id?: string | null;
  auth_method?: string;
  expires_at?: string | null;
};

export type AuthSessionResponse = AuthRoleResponse & {
  authenticated: boolean;
};

export type PrincipalClientRole = "end_user" | "viewer" | "technician" | "admin";

export type PrincipalCredential = {
  credential_hash_prefix: string;
  active: boolean;
  created_at: string;
};

export type PrincipalAdminView = {
  principal_id: string;
  kind: "customer" | "staff";
  display_name: string;
  active: boolean;
  created_at: string;
  client_roles: Array<[string, PrincipalClientRole]>;
  global_roles: string[];
  credential_count: number;
  credentials: PrincipalCredential[];
  identities: PrincipalIdentity[];
};

export type PrincipalIdentity = {
  issuer: string;
  subject: string;
  subject_kind: "oid" | "email";
  created_at: string;
  last_login_at: string | null;
};

export type OidcConfig = {
  enabled: boolean;
  tenant_id: string;
  client_id: string;
  public_base_url: string;
  auto_provision_enabled: boolean;
  auto_provision_tenant_id: string;
  auto_provision_client_id: string;
  auto_provision_role: "viewer";
  client_secret_configured: boolean;
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
