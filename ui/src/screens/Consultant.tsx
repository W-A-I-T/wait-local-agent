import { FormEvent, useCallback, useEffect, useState } from "react";
import { AlertTriangle, Compass, RefreshCw } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useDashboard } from "../app/DashboardContext";
import { ClientIdSelect } from "../components/ClientIdSelect";
import {
  ApiRequestError,
  CLIENT_SCOPE_ERROR_MESSAGE,
  apiFetch,
  isCapabilityRequiredDetail,
  isClientScopeErrorDetail,
  shouldSuppressClientScopeError,
} from "../api/client";
import { StatusChip } from "../components/StatusChip";
import { humanizeName } from "../lib/fields";
import { collectHandoffArtifacts, SOLUTION_DELIVERY_ROUTE } from "../lib/solutionDeliveryHandoff";
import type {
  ArchitectureDecision,
  ConsultantArchitecture,
  ConsultantArchitectureComponent,
  ConsultantBlueprint,
  ConsultantBlueprintPromotionResult,
  ConsultantConnectorArtifact,
  ConsultantConnectorValidationResult,
  ConsultantCopilotStudioPlan,
  ConsultantDiscoveryResult,
  ConsultantDiscoverySession,
  ConsultantDeliveryPlan,
  ConsultantEnvironmentResult,
  ConsultantEmployeeOnboardingDemo,
  ConsultantEvaluationResult,
  ConsultantGovernanceResult,
  ConsultantMonitoring,
  ConsultantSupervisorPlan,
  ConsultantSupervisorRun,
  ConsultantUseCase,
  MspPlaybookEntry,
  PowerAppsArtifact,
  PowerAutomateFlowPlan,
} from "../api/types";

const DEFAULT_POWER_APPS_ENTITIES = JSON.stringify([
  {
    logical_name: "employee",
    display_name: "Employee",
    fields: [
      { name: "display_name", type: "string", required: true },
      { name: "start_date", type: "date", required: true },
    ],
  },
], null, 2);
const DEFAULT_POWER_APPS_SCREENS = JSON.stringify([
  { id: "employee_browse", title: "Employees", entity: "employee", mode: "browse" },
  { id: "employee_edit", title: "Edit employee", entity: "employee", mode: "edit" },
], null, 2);
const DEFAULT_POWER_APPS_ACTIONS = JSON.stringify([
  { id: "employee_lookup", connector_id: "m365", method: "GET" },
  { id: "employee_create", connector_id: "m365", method: "POST", approval_required: true },
], null, 2);

const ENVIRONMENT_SYSTEMS = [
  "HaloPSA",
  "Hudu",
  "IT Glue",
  "Confluence Cloud",
  "Notion",
  "SharePoint",
  "ConnectWise PSA",
  "Syncro",
  "ServiceNow",
  "Autotask PSA",
  "Microsoft 365 / Entra",
  "TimeZest",
  "ScalePad",
];

type ConsultantSection =
  | "blueprints"
  | "blueprintDetail"
  | "discoverySessions"
  | "environment"
  | "governance"
  | "evaluations"
  | "deliveryPlan"
  | "supervisor"
  | "useCases"
  | "monitoring"
  | "copilotStudio"
  | "connector";
type SectionLoadStatus = "loading" | "ready" | "empty" | "gated" | "error";
type SectionLoadState = { status: SectionLoadStatus; detail?: string };
type SectionLoadStates = Record<ConsultantSection, SectionLoadState>;

const SECTION_DETAILS: Record<ConsultantSection, { label: string; pack: string; retryLabel: string }> = {
  blueprints: { label: "solution blueprints", pack: "Microsoft Admin", retryLabel: "blueprints" },
  blueprintDetail: { label: "blueprint detail", pack: "Microsoft Admin", retryLabel: "blueprint detail" },
  discoverySessions: { label: "guided discovery sessions", pack: "Microsoft Admin", retryLabel: "discovery sessions" },
  environment: { label: "environment evidence", pack: "Microsoft Admin", retryLabel: "environment probe" },
  governance: { label: "governance review", pack: "Microsoft Admin", retryLabel: "governance review" },
  evaluations: { label: "agent evaluation", pack: "Microsoft Admin", retryLabel: "evaluation" },
  deliveryPlan: { label: "delivery plan", pack: "Microsoft Admin", retryLabel: "delivery plan" },
  supervisor: { label: "supervisor delegation", pack: "Microsoft Admin", retryLabel: "supervisor delegation" },
  useCases: { label: "Solutions Architect use cases", pack: "Microsoft Admin", retryLabel: "use cases" },
  monitoring: { label: "agent monitoring", pack: "Microsoft Admin", retryLabel: "monitoring" },
  copilotStudio: { label: "Copilot Studio planner", pack: "Microsoft Admin", retryLabel: "Copilot Studio plan" },
  connector: { label: "custom connector", pack: "Microsoft Admin", retryLabel: "connector validation" },
};

const INITIAL_SECTION_STATES: SectionLoadStates = {
  blueprints: { status: "loading" },
  blueprintDetail: { status: "empty" },
  discoverySessions: { status: "loading" },
  environment: { status: "empty" },
  governance: { status: "empty" },
  evaluations: { status: "empty" },
  deliveryPlan: { status: "empty" },
  supervisor: { status: "empty" },
  useCases: { status: "loading" },
  monitoring: { status: "loading" },
  copilotStudio: { status: "empty" },
  connector: { status: "empty" },
};

type CopilotTopicDraft = { name: string; triggerPhrases: string[]; triggerInput: string };
type CopilotActionDraft = { id: string; connectorId: string; method: string; approvalRequired: boolean };

const MAX_COPILOT_TOPICS = 32;
const MAX_COPILOT_TRIGGERS = 16;
const MAX_COPILOT_KNOWLEDGE_SOURCES = 32;
const MAX_COPILOT_ACTIONS = 32;
const MAX_CONNECTOR_DEFINITION_BYTES = 1_000_000;
const DEFAULT_CONNECTOR_DEFINITION = JSON.stringify({
  swagger: "2.0",
  info: { title: "Customer API", version: "1.0" },
  host: "api.example.com",
  schemes: ["https"],
  paths: {
    "/customers": {
      get: {
        operationId: "list_customers",
        summary: "List customers",
        responses: { "200": { description: "Customers" } },
      },
    },
  },
}, null, 2);

function sectionStateForError(error: unknown, clientScopeIds?: string[] | null, isMspAdmin?: boolean): SectionLoadState {
  if (shouldSuppressClientScopeError(error, clientScopeIds, isMspAdmin)) {
    return { status: "empty" };
  }
  if (error instanceof ApiRequestError && error.status === 403) {
    const detail = error.detail ?? apiRequestReason(error);
    if (isCapabilityRequiredDetail(detail)) {
      return {
        status: "gated",
        detail: typeof detail.remediation === "string" ? detail.remediation : undefined,
      };
    }
    return {
      status: "error",
      detail: isClientScopeErrorDetail(detail) ? CLIENT_SCOPE_ERROR_MESSAGE : error.message,
    };
  }
  if (error instanceof ApiRequestError && error.status === 404) {
    return { status: "empty" };
  }
  return {
    status: "error",
    detail: error instanceof ApiRequestError && (error.status === 409 || error.status === 422)
      ? apiRequestReason(error)
      : error instanceof Error ? error.message : "The section could not be loaded.",
  };
}

function apiRequestReason(error: ApiRequestError): string {
  const separator = error.technicalDetail.lastIndexOf(": ");
  return separator >= 0 ? error.technicalDetail.slice(separator + 2) : error.message;
}

function SectionLoadNotice({
  section,
  state,
  onRetry,
}: {
  section: ConsultantSection;
  state: SectionLoadState;
  onRetry: () => void;
}) {
  const details = SECTION_DETAILS[section];
  if (state.status === "gated") {
    return (
      <div className="notice" role="status">
        <span>Requires the {details.pack} pack or Microsoft Admin capability.</span>{state.detail ? " " + state.detail : ""} <Link to="/system/extensions">Open Extensions / Packs</Link>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="notice danger" role="alert">
        Unable to load {details.label}. {state.detail} <button type="button" onClick={onRetry}>Retry {details.retryLabel}</button>
      </div>
    );
  }
  return null;
}

export function Consultant() {
  const {
    canWrite,
    clients = [],
    clientId: scopedClientId,
    selectedClientId,
    authState,
    writeHealth,
    clientScopeIds,
    isMspAdmin,
  } = useDashboard();
  const navigate = useNavigate();
  const [blueprints, setBlueprints] = useState<ConsultantBlueprint[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [blueprintDetail, setBlueprintDetail] = useState<ConsultantBlueprint | null>(null);
  const [architecture, setArchitecture] = useState<ConsultantArchitecture | null>(null);
  const [workflowDrafts, setWorkflowDrafts] = useState<Record<string, { trigger: string; steps: string[] }>>({});
  const [useCases, setUseCases] = useState<ConsultantUseCase[]>([]);
  const [monitoring, setMonitoring] = useState<ConsultantMonitoring | null>(null);
  const [employeeOnboardingDemo, setEmployeeOnboardingDemo] = useState<ConsultantEmployeeOnboardingDemo | null>(null);
  const [employeeOnboardingEntityId, setEmployeeOnboardingEntityId] = useState("TCK-1001");
  const [employeeOnboardingLoading, setEmployeeOnboardingLoading] = useState(false);
  const [flowPlan, setFlowPlan] = useState<PowerAutomateFlowPlan | null>(null);
  const [powerAppsArtifact, setPowerAppsArtifact] = useState<PowerAppsArtifact | null>(null);
  const [powerAppsLoading, setPowerAppsLoading] = useState(false);
  const [powerAppsName, setPowerAppsName] = useState("Employee onboarding workspace");
  const [powerAppsEntities, setPowerAppsEntities] = useState(DEFAULT_POWER_APPS_ENTITIES);
  const [powerAppsScreens, setPowerAppsScreens] = useState(DEFAULT_POWER_APPS_SCREENS);
  const [powerAppsActions, setPowerAppsActions] = useState(DEFAULT_POWER_APPS_ACTIONS);
  const [copilotName, setCopilotName] = useState("Support assistant");
  const [copilotBusinessGoal, setCopilotBusinessGoal] = useState("Help operators answer bounded customer support questions.");
  const [copilotTopics, setCopilotTopics] = useState<CopilotTopicDraft[]>([
    { name: "Ticket status", triggerPhrases: ["check my ticket"], triggerInput: "" },
  ]);
  const [copilotKnowledgeSources, setCopilotKnowledgeSources] = useState<string[]>([]);
  const [copilotActions, setCopilotActions] = useState<CopilotActionDraft[]>([]);
  const [copilotPlan, setCopilotPlan] = useState<ConsultantCopilotStudioPlan | null>(null);
  const [copilotLoading, setCopilotLoading] = useState(false);
  const [connectorId, setConnectorId] = useState("customer-api");
  const [connectorDefinition, setConnectorDefinition] = useState(DEFAULT_CONNECTOR_DEFINITION);
  const [connectorArtifact, setConnectorArtifact] = useState<ConsultantConnectorArtifact | null>(null);
  const [connectorErrors, setConnectorErrors] = useState<string[]>([]);
  const [connectorAction, setConnectorAction] = useState<"validate" | "generate" | null>(null);
  const [connectorLastAction, setConnectorLastAction] = useState<"validate" | "generate">("validate");
  const [flowLoading, setFlowLoading] = useState(false);
  const [discoveryGoal, setDiscoveryGoal] = useState("");
  const [discoveryClientId, setDiscoveryClientId] = useState("");
  const [discoverySolutionName, setDiscoverySolutionName] = useState("");
  const [discoveryRisk, setDiscoveryRisk] = useState<"low" | "medium" | "high">("medium");
  const [discoveryUsers, setDiscoveryUsers] = useState("");
  const [discoverySystems, setDiscoverySystems] = useState("");
  const [discoveryKnowledge, setDiscoveryKnowledge] = useState("");
  const [discoveryChanges, setDiscoveryChanges] = useState("");
  const [discoveryApprovals, setDiscoveryApprovals] = useState("");
  const [discoveryFailure, setDiscoveryFailure] = useState("");
  const [discoveryDataLocation, setDiscoveryDataLocation] = useState("");
  const [discoveryLeavesTenant, setDiscoveryLeavesTenant] = useState(false);
  const [discoveryResult, setDiscoveryResult] = useState<ConsultantDiscoveryResult | null>(null);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoverySession, setDiscoverySession] = useState<ConsultantDiscoverySession | null>(null);
  const [discoverySessions, setDiscoverySessions] = useState<ConsultantDiscoverySession[]>([]);
  const [guidedAnswer, setGuidedAnswer] = useState("");
  const [guidedBooleanAnswer, setGuidedBooleanAnswer] = useState(false);
  const [guidedLoading, setGuidedLoading] = useState(false);
  const [promotionLoading, setPromotionLoading] = useState(false);
  const [playbookLoading, setPlaybookLoading] = useState(false);
  const [playbookNotice, setPlaybookNotice] = useState("");
  const [environmentResult, setEnvironmentResult] = useState<ConsultantEnvironmentResult | null>(null);
  const [governanceResult, setGovernanceResult] = useState<ConsultantGovernanceResult | null>(null);
  const [governanceArtifacts, setGovernanceArtifacts] = useState("[]");
  const [evaluationResult, setEvaluationResult] = useState<ConsultantEvaluationResult | null>(null);
  const [evaluationMode, setEvaluationMode] = useState<"contract" | "controlled">("contract");
  const [evaluationCaseId, setEvaluationCaseId] = useState("architecture-review");
  const [evaluationExpectedTools, setEvaluationExpectedTools] = useState("");
  const [evaluationExpectedApprovals, setEvaluationExpectedApprovals] = useState("");
  const [evaluationObservedTools, setEvaluationObservedTools] = useState("");
  const [evaluationObservedApprovals, setEvaluationObservedApprovals] = useState("");
  const [evaluationAgentId, setEvaluationAgentId] = useState("");
  const [evaluationEntityId, setEvaluationEntityId] = useState("TCK-1001");
  const [deliveryTargets, setDeliveryTargets] = useState("Teams, Power Automate, Power Apps, Dataverse");
  const [deliveryResult, setDeliveryResult] = useState<ConsultantDeliveryPlan | null>(null);
  const [supervisorTask, setSupervisorTask] = useState("");
  const [supervisorEntityId, setSupervisorEntityId] = useState("TCK-1001");
  const [supervisorMaxRetries, setSupervisorMaxRetries] = useState("0");
  const [supervisorPlan, setSupervisorPlan] = useState<ConsultantSupervisorPlan | null>(null);
  const [supervisorRun, setSupervisorRun] = useState<ConsultantSupervisorRun | null>(null);
  const [supervisorCompletedRunIds, setSupervisorCompletedRunIds] = useState<number[]>([]);
  const [supervisorAction, setSupervisorAction] = useState<"plan" | "run" | "cancel" | "retry" | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [sectionStates, setSectionStates] = useState<SectionLoadStates>(INITIAL_SECTION_STATES);

  const setSectionState = useCallback((section: ConsultantSection, state: SectionLoadState) => {
    setSectionStates((current) => ({ ...current, [section]: state }));
  }, []);

  const loadBlueprints = useCallback(async () => {
    setSectionState("blueprints", { status: "loading" });
    try {
      const result = await apiFetch<ConsultantBlueprint[]>("/consultant/blueprints");
      const rows = Array.isArray(result) ? result : [];
      setBlueprints(rows);
      setSelectedId((currentSelectedId) => (
        currentSelectedId && rows.some((row) => row.id === currentSelectedId)
          ? currentSelectedId
          : rows[0]?.id ?? null
      ));
      setArchitecture((currentArchitecture) => (
        currentArchitecture && rows.some((row) => row.id === currentArchitecture.blueprint_id)
          ? currentArchitecture
          : null
      ));
      setSectionState("blueprints", { status: rows.length ? "ready" : "empty" });
    } catch (error) {
      setSectionState("blueprints", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }, [clientScopeIds, isMspAdmin, setSectionState]);

  const loadUseCases = useCallback(async () => {
    setSectionState("useCases", { status: "loading" });
    try {
      const result = await apiFetch<{ use_cases: ConsultantUseCase[] }>("/consultant/use-cases");
      const rows = Array.isArray(result.use_cases) ? result.use_cases : [];
      setUseCases(rows);
      setSectionState("useCases", { status: rows.length ? "ready" : "empty" });
    } catch (error) {
      setSectionState("useCases", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }, [clientScopeIds, isMspAdmin, setSectionState]);

  const loadMonitoring = useCallback(async () => {
    setSectionState("monitoring", { status: "loading" });
    try {
      const result = await apiFetch<ConsultantMonitoring>("/consultant/monitoring/agents");
      setMonitoring(result);
      setSectionState("monitoring", { status: "ready" });
    } catch (error) {
      setSectionState("monitoring", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }, [clientScopeIds, isMspAdmin, setSectionState]);

  const loadDiscoverySessions = useCallback(async () => {
    setSectionState("discoverySessions", { status: "loading" });
    try {
      const result = await apiFetch<ConsultantDiscoverySession[]>("/consultant/discovery/sessions");
      const rows = Array.isArray(result) ? result : [];
      setDiscoverySessions(rows);
      setSectionState("discoverySessions", { status: rows.length ? "ready" : "empty" });
    } catch (error) {
      setSectionState("discoverySessions", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }, [clientScopeIds, isMspAdmin, setSectionState]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([loadBlueprints(), loadUseCases(), loadMonitoring(), loadDiscoverySessions()]);
    } finally {
      setLoading(false);
    }
  }, [loadBlueprints, loadDiscoverySessions, loadMonitoring, loadUseCases]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function inspectBlueprint(blueprintId: string) {
    setSelectedId(blueprintId);
    setSectionState("blueprintDetail", { status: "loading" });
    setBlueprintDetail(null);
    setArchitecture(null);
    setFlowPlan(null);
    setEnvironmentResult(null);
    setGovernanceResult(null);
    setEvaluationResult(null);
    setDeliveryResult(null);
    setCopilotPlan(null);
    setSectionState("copilotStudio", { status: "empty" });
    setConnectorArtifact(null);
    setConnectorErrors([]);
    setSectionState("connector", { status: "empty" });
    setSupervisorTask("");
    setSupervisorPlan(null);
    setSupervisorRun(null);
    setSupervisorCompletedRunIds([]);
    setSupervisorAction(null);
    setSectionState("environment", { status: "empty" });
    setSectionState("governance", { status: "empty" });
    setSectionState("evaluations", { status: "empty" });
    setSectionState("deliveryPlan", { status: "empty" });
    setSectionState("supervisor", { status: "empty" });
    setMessage("");
    setPlaybookNotice("");
    void apiFetch<ConsultantBlueprint>(
      `/consultant/blueprints/${encodeURIComponent(blueprintId)}`,
    ).then((result) => {
      setBlueprintDetail(result);
      setSectionState("blueprintDetail", { status: "ready" });
    }).catch((error: unknown) => {
      setSectionState("blueprintDetail", sectionStateForError(error, clientScopeIds, isMspAdmin));
    });
    try {
      const result = await apiFetch<ConsultantArchitecture>(
        `/consultant/blueprints/${encodeURIComponent(blueprintId)}/architecture`
      );
      setArchitecture(result);
      setSupervisorTask(result.solution.name);
      setWorkflowDrafts(Object.fromEntries(
        result.components
          .filter((component) => component.kind === "workflow")
          .map((component) => [component.id, {
            trigger: component.trigger ?? "",
            steps: [...(component.steps ?? [])],
          }]),
      ));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to build the architecture view.");
    }
  }

  function supervisorRequestValues(requireEntityId = false) {
    const clientId = currentClientId();
    const task = supervisorTask.trim();
    const entityId = supervisorEntityId.trim();
    const childAgentIds = architecture?.supervisor?.children.map((child) => child.id) ?? [];
    const rawMaxRetries = supervisorMaxRetries.trim();
    const maxRetries = Number(rawMaxRetries);
    if (!clientId || !task || (requireEntityId && !entityId) || childAgentIds.length === 0) {
      setSectionState("supervisor", { status: "error", detail: requireEntityId
        ? "A tenant scope, delegation task, existing ticket ID, and at least one child agent are required."
        : "A tenant scope, delegation task, and at least one child agent are required." });
      return null;
    }
    if (!rawMaxRetries || !Number.isInteger(maxRetries) || maxRetries < 0 || maxRetries > 3) {
      setSectionState("supervisor", { status: "error", detail: "Maximum retries per child must be a whole number from 0 through 3." });
      return null;
    }
    return { clientId, task, entityId, childAgentIds, maxRetries };
  }

  async function planSupervisorDelegation() {
    const values = supervisorRequestValues();
    if (!values) return;
    setSupervisorAction("plan");
    setSectionState("supervisor", { status: "loading" });
    setSupervisorPlan(null);
    setSupervisorRun(null);
    setSupervisorCompletedRunIds([]);
    try {
      const result = await apiFetch<ConsultantSupervisorPlan>("/consultant/supervisor/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: values.clientId,
          task: values.task,
          child_agent_ids: values.childAgentIds,
          max_retries: values.maxRetries,
        }),
      });
      setSupervisorPlan(result);
      setSectionState("supervisor", { status: "ready" });
    } catch (error) {
      setSectionState("supervisor", sectionStateForError(error, clientScopeIds, isMspAdmin));
    } finally {
      setSupervisorAction(null);
    }
  }

  async function runSupervisorDelegation(action: "run" | "cancel" | "retry" = "run") {
    const values = supervisorRequestValues(true);
    if (!values) return;
    if (!supervisorPlan) {
      setSectionState("supervisor", { status: "error", detail: "Plan the delegation before running it." });
      return;
    }
    const pendingRunId = supervisorRun?.resumption.pending_run_id;
    if (action === "cancel" && pendingRunId == null) {
      setSectionState("supervisor", { status: "error", detail: "There is no approval-paused child run to cancel." });
      return;
    }
    setSupervisorAction(action);
    setSectionState("supervisor", { status: "loading" });
    try {
      const result = await apiFetch<ConsultantSupervisorRun>("/consultant/supervisor/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: values.clientId,
          entity_id: values.entityId,
          task: values.task,
          child_agent_ids: values.childAgentIds,
          input: { ticket_id: values.entityId },
          completed_run_ids: supervisorCompletedRunIds,
          max_retries: values.maxRetries,
          ...(action === "cancel" ? { cancel_run_id: pendingRunId } : {}),
        }),
      });
      setSupervisorRun(result);
      setSupervisorCompletedRunIds(result.resumption.completed_run_ids);
      setSectionState("supervisor", { status: "ready" });
    } catch (error) {
      setSectionState("supervisor", sectionStateForError(error, clientScopeIds, isMspAdmin));
    } finally {
      setSupervisorAction(null);
    }
  }

  async function probeEnvironment() {
    const clientId = currentClientId();
    if (!clientId) {
      setMessage("Select a blueprint or provide a tenant scope before probing the environment.");
      return;
    }
    setSectionState("environment", { status: "loading" });
    setEnvironmentResult(null);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantEnvironmentResult>("/consultant/environment-discovery", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId, systems: ENVIRONMENT_SYSTEMS, probe: true }),
      });
      setEnvironmentResult(result);
      setSectionState("environment", { status: result.systems.length ? "ready" : "empty" });
    } catch (error) {
      setSectionState("environment", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }

  async function evaluateGovernance(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!architecture) {
      setSectionState("governance", { status: "empty" });
      return;
    }
    let connectorArtifacts: Record<string, unknown>[];
    try {
      connectorArtifacts = parseJsonArray(governanceArtifacts, "Connector artifacts");
    } catch (error) {
      setSectionState("governance", { status: "error", detail: error instanceof Error ? error.message : "Connector artifacts are invalid." });
      return;
    }
    setSectionState("governance", { status: "loading" });
    setGovernanceResult(null);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantGovernanceResult>("/consultant/governance/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ architecture, connector_artifacts: connectorArtifacts }),
      });
      setGovernanceResult(result);
      setSectionState("governance", { status: "ready" });
    } catch (error) {
      setSectionState("governance", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }

  async function runEvaluation(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const clientId = currentClientId();
    const caseId = evaluationCaseId.trim();
    if (!clientId || !caseId) {
      setSectionState("evaluations", { status: "error", detail: "A tenant scope and evaluation case ID are required." });
      return;
    }
    if (evaluationMode === "controlled" && !(authState === "demo" && writeHealth?.status === "blocked")) {
      setSectionState("evaluations", { status: "error", detail: "Controlled local execution is available only in demo mode with Safe Mode writes disabled." });
      return;
    }
    if (evaluationMode === "controlled" && (!evaluationAgentId.trim() || !evaluationEntityId.trim())) {
      setSectionState("evaluations", { status: "error", detail: "A tenant-scoped agent ID and entity ID are required for controlled evaluation." });
      return;
    }
    const testCase = {
      id: caseId,
      expected_tool_ids: splitList(evaluationExpectedTools),
      forbidden_tool_ids: [],
      expected_approval_tool_ids: splitList(evaluationExpectedApprovals),
    };
    const body: Record<string, unknown> = {
      test_set: [testCase],
      observations: {
        [caseId]: {
          tool_ids: splitList(evaluationObservedTools),
          approval_tool_ids: splitList(evaluationObservedApprovals),
          tenant_isolated: true,
          prompt_injection_blocked: true,
        },
      },
    };
    if (evaluationMode === "controlled") {
      body.execution = {
        agent_id: evaluationAgentId.trim(),
        entity_id: evaluationEntityId.trim(),
        client_id: clientId,
      };
    }
    setSectionState("evaluations", { status: "loading" });
    setEvaluationResult(null);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantEvaluationResult>("/consultant/evaluations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setEvaluationResult(result);
      setSectionState("evaluations", { status: "ready" });
    } catch (error) {
      setSectionState("evaluations", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }

  async function buildDeliveryPlan(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const clientId = currentClientId();
    const targets = splitList(deliveryTargets);
    if (!clientId || !architecture || !governanceResult || !evaluationResult) {
      setSectionState("deliveryPlan", { status: "error", detail: "Complete governance and evaluation review before creating the delivery plan." });
      return;
    }
    if (!targets.length) {
      setSectionState("deliveryPlan", { status: "error", detail: "At least one deployment target is required." });
      return;
    }
    let connectorArtifacts: Record<string, unknown>[];
    try {
      connectorArtifacts = parseJsonArray(governanceArtifacts, "Connector artifacts");
    } catch (error) {
      setSectionState("deliveryPlan", { status: "error", detail: error instanceof Error ? error.message : "Connector artifacts are invalid." });
      return;
    }
    setSectionState("deliveryPlan", { status: "loading" });
    setDeliveryResult(null);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantDeliveryPlan>("/consultant/delivery-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          architecture,
          evaluation: evaluationResult,
          governance: governanceResult,
          deployment_targets: targets,
          connector_artifacts: connectorArtifacts,
          review_artifacts: environmentResult ? [environmentResult] : [],
        }),
      });
      setDeliveryResult(result);
      setSectionState("deliveryPlan", { status: "ready" });
    } catch (error) {
      setSectionState("deliveryPlan", sectionStateForError(error, clientScopeIds, isMspAdmin));
    }
  }

  async function generatePlaybook() {
    if (!selectedId) return;
    setPlaybookLoading(true);
    setPlaybookNotice("");
    setMessage("");
    try {
      await apiFetch<MspPlaybookEntry>(
        `/consultant/blueprints/${encodeURIComponent(selectedId)}/generate-playbook`,
        { method: "POST" },
      );
      setPlaybookNotice("Draft playbook generated (disabled) — review and enable it in Playbooks.");
    } catch (error) {
      setPlaybookNotice("");
      setMessage(error instanceof Error ? error.message : "Unable to generate the playbook.");
    } finally {
      setPlaybookLoading(false);
    }
  }

  async function preparePowerAutomatePlan(workflow: ConsultantArchitectureComponent) {
    if (!selected) return;
    const draft = workflowDrafts[workflow.id] ?? {
      trigger: workflow.trigger ?? "Manual review request",
      steps: workflow.steps ?? [],
    };
    setFlowLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<PowerAutomateFlowPlan>("/consultant/workflows/power-automate/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: selected.client_id,
          workflow_id: powerAutomateIdentifier(workflow.id),
          workflow_name: workflow.name ?? workflow.id,
          trigger: draft.trigger || "Manual review request",
          steps: draft.steps.map((name, index) => ({
            id: `step_${index + 1}`,
            name,
            kind: "action",
            method: "GET",
          })),
        }),
      });
      setFlowPlan(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to prepare the Power Automate plan.");
    } finally {
      setFlowLoading(false);
    }
  }

  function updateWorkflowDraft(workflowId: string, draft: { trigger: string; steps: string[] }) {
    setWorkflowDrafts((current) => ({ ...current, [workflowId]: draft }));
  }

  async function assessDiscovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clientId = currentClientId();
    if (!clientId || !discoveryGoal.trim()) {
      setMessage("A tenant scope and business goal are required before assessing discovery.");
      return;
    }
    setDiscoveryLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantDiscoveryResult>("/consultant/discovery", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          answers: {
            solution_name: discoverySolutionName.trim() || undefined,
            business_goal: discoveryGoal,
            users: splitList(discoveryUsers),
            systems: splitList(discoverySystems),
            knowledge: splitList(discoveryKnowledge),
            reads: splitList(discoveryKnowledge),
            changes: splitList(discoveryChanges),
            approvals: splitList(discoveryApprovals),
            failure_handling: discoveryFailure || undefined,
            data_location: splitList(discoveryDataLocation),
            data_leaves_tenant: discoveryLeavesTenant,
          },
        }),
      });
      setDiscoveryResult(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to assess discovery.");
    } finally {
      setDiscoveryLoading(false);
    }
  }

  async function startGuidedDiscovery() {
    const clientId = currentClientId();
    if (!clientId || !discoveryGoal.trim()) {
      setMessage("A tenant scope and business goal are required before starting guided discovery.");
      return;
    }
    setGuidedLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantDiscoverySession>("/consultant/discovery/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          opening_message: discoveryGoal.trim(),
          answers: { solution_name: discoverySolutionName.trim() || undefined },
        }),
      });
      setDiscoverySession(result);
      setDiscoveryResult(result);
      setDiscoverySessions((current) => [result, ...current.filter((item) => item.session_id !== result.session_id)]);
      setGuidedAnswer("");
      setGuidedBooleanAnswer(false);
      if (result.blueprint_id) {
        setMessage(`Discovery completed and blueprint ${result.blueprint_id} was saved for review.`);
        await refresh();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start guided discovery.");
    } finally {
      setGuidedLoading(false);
    }
  }

  async function answerGuidedDiscovery() {
    const question = discoverySession?.next_question;
    if (!question) return;
    const clientId = currentClientId();
    if (!clientId) return;
    const answer = question.kind === "boolean"
      ? guidedBooleanAnswer
      : question.kind === "list" ? splitList(guidedAnswer) : guidedAnswer.trim();
    if (question.kind !== "boolean" && !guidedAnswer.trim()) {
      setMessage("Provide an explicit answer before continuing guided discovery.");
      return;
    }
    setGuidedLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantDiscoverySession>(
        `/consultant/discovery/sessions/${encodeURIComponent(discoverySession.session_id)}/turn`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: clientId, field: question.id, answer }),
        },
      );
      setDiscoverySession(result);
      setDiscoveryResult(result);
      setDiscoverySessions((current) => [result, ...current.filter((item) => item.session_id !== result.session_id)]);
      setGuidedAnswer("");
      setGuidedBooleanAnswer(false);
      if (result.blueprint_id) {
        setMessage(`Discovery completed and blueprint ${result.blueprint_id} was saved for review.`);
        await refresh();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to record the discovery answer.");
    } finally {
      setGuidedLoading(false);
    }
  }

  async function resumeGuidedDiscovery(sessionId: string) {
    const clientId = currentClientId();
    if (!clientId) return;
    setGuidedLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantDiscoverySession>(
        `/consultant/discovery/sessions/${encodeURIComponent(sessionId)}`,
      );
      setDiscoverySession(result);
      setDiscoveryResult(result);
      const answers = result.answered ?? {};
      if (typeof answers.solution_name === "string") setDiscoverySolutionName(answers.solution_name);
      if (typeof answers.business_goal === "string") setDiscoveryGoal(answers.business_goal);
      setGuidedAnswer("");
      setGuidedBooleanAnswer(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to resume guided discovery.");
    } finally {
      setGuidedLoading(false);
    }
  }

  function startNewGuidedDiscovery() {
    setDiscoverySession(null);
    setDiscoveryResult(null);
    setGuidedAnswer("");
    setGuidedBooleanAnswer(false);
    setMessage("");
  }

  async function promoteDiscovery() {
    const clientId = resolveClientId(selected?.client_id, scopedClientId, selectedClientId, discoveryClientId || blueprints[0]?.client_id);
    if (!clientId || !discoveryResult || discoveryResult.readiness !== "ready_for_architecture") {
      setMessage("Complete the required discovery evidence before saving a solution blueprint.");
      return;
    }
    if (!discoverySolutionName.trim()) {
      setMessage("Provide a solution name before saving a solution blueprint.");
      return;
    }
    if (!discoveryResult.answered) {
      setMessage("Discovery answers are unavailable; reassess the intake before saving the blueprint.");
      return;
    }
    setPromotionLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantBlueprintPromotionResult>("/consultant/discovery/promote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          solution_name: discoverySolutionName.trim(),
          risk: discoveryRisk,
          answers: discoveryResult.answered,
        }),
      });
      setBlueprints((current) => [
        result.blueprint,
        ...current.filter((blueprint) => blueprint.id !== result.blueprint.id),
      ]);
      setSelectedId(result.blueprint.id);
      setArchitecture(null);
      setMessage("Solution blueprint saved for architecture review.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save the solution blueprint.");
    } finally {
      setPromotionLoading(false);
    }
  }

  async function buildPowerAppsArtifact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clientId = currentClientId();
    if (!clientId || !powerAppsName.trim()) {
      setMessage("Choose a blueprint tenant and provide an app name before building the artifact.");
      return;
    }
    try {
      const entities = parseJsonArray(powerAppsEntities, "Dataverse tables");
      const screens = parseJsonArray(powerAppsScreens, "Canvas screens");
      const actions = parseJsonArray(powerAppsActions, "Connector actions");
      setPowerAppsLoading(true);
      setMessage("");
      const result = await apiFetch<PowerAppsArtifact>("/consultant/power-apps/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          app_name: powerAppsName,
          entities,
          screens,
          actions,
        }),
      });
      setPowerAppsArtifact(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to build the Power Apps artifact.");
    } finally {
      setPowerAppsLoading(false);
    }
  }

  function updateCopilotTopic(index: number, update: Partial<CopilotTopicDraft>) {
    setCopilotTopics((current) => current.map((topic, topicIndex) => topicIndex === index ? { ...topic, ...update } : topic));
  }

  function addCopilotTopic() {
    if (copilotTopics.length < MAX_COPILOT_TOPICS) {
      setCopilotTopics((current) => [...current, { name: "", triggerPhrases: [], triggerInput: "" }]);
    }
  }

  function removeCopilotTopic(index: number) {
    setCopilotTopics((current) => current.filter((_, topicIndex) => topicIndex !== index));
  }

  function addCopilotTrigger(index: number) {
    const phrase = copilotTopics[index]?.triggerInput.trim();
    if (!phrase || copilotTopics[index].triggerPhrases.length >= MAX_COPILOT_TRIGGERS) return;
    if (copilotTopics[index].triggerPhrases.includes(phrase)) {
      updateCopilotTopic(index, { triggerInput: "" });
      return;
    }
    updateCopilotTopic(index, {
      triggerPhrases: [...copilotTopics[index].triggerPhrases, phrase],
      triggerInput: "",
    });
  }

  function addCopilotAction() {
    if (copilotActions.length < MAX_COPILOT_ACTIONS) {
      setCopilotActions((current) => [...current, { id: "", connectorId: "", method: "GET", approvalRequired: false }]);
    }
  }

  function updateCopilotAction(index: number, update: Partial<CopilotActionDraft>) {
    setCopilotActions((current) => current.map((action, actionIndex) => actionIndex === index ? { ...action, ...update } : action));
  }

  function removeCopilotAction(index: number) {
    setCopilotActions((current) => current.filter((_, actionIndex) => actionIndex !== index));
  }

  async function buildCopilotStudioPlan(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const clientId = currentClientId();
    const copilotNameValue = copilotName.trim();
    const businessGoal = copilotBusinessGoal.trim();
    if (!clientId || !copilotNameValue || !businessGoal) {
      setSectionState("copilotStudio", { status: "error", detail: "A tenant scope, agent name, and description are required." });
      return;
    }
    if (copilotTopics.some((topic) => !topic.name.trim())) {
      setSectionState("copilotStudio", { status: "error", detail: "Each topic needs a name before the plan can be created." });
      return;
    }
    if (copilotActions.some((action) => !action.id.trim() || !action.connectorId.trim())) {
      setSectionState("copilotStudio", { status: "error", detail: "Each action needs an ID and connector ID before the plan can be created." });
      return;
    }
    const topicIds = uniqueCopilotIdentifiers(copilotTopics.map((topic) => topic.name), "topic");
    const actionIds = uniqueCopilotIdentifiers(copilotActions.map((action) => action.id), "action");
    const connectorIds = uniqueCopilotIdentifiers(copilotActions.map((action) => action.connectorId), "connector");
    const body = {
      client_id: clientId,
      copilot_name: copilotNameValue,
      business_goal: businessGoal,
      topics: copilotTopics.map((topic, index) => ({
        id: topicIds[index],
        name: topic.name.trim(),
        trigger_phrases: topic.triggerPhrases,
      })),
      knowledge_sources: copilotKnowledgeSources.map((source) => source.trim()).filter(Boolean),
      actions: copilotActions.map((action, index) => ({
        id: actionIds[index],
        connector_id: connectorIds[index],
        method: action.method,
        approval_required: action.method === "GET" ? action.approvalRequired : true,
      })),
    };
    setCopilotLoading(true);
    setCopilotPlan(null);
    setSectionState("copilotStudio", { status: "loading" });
    try {
      const result = await apiFetch<ConsultantCopilotStudioPlan>("/consultant/copilot-studio/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setCopilotPlan(result);
      setSectionState("copilotStudio", { status: "ready" });
    } catch (error) {
      setSectionState("copilotStudio", sectionStateForError(error, clientScopeIds, isMspAdmin));
    } finally {
      setCopilotLoading(false);
    }
  }

  async function runConnectorAction(action: "validate" | "generate") {
    setConnectorLastAction(action);
    const client = connectorId.trim();
    if (!client) {
      setConnectorErrors(["A connector ID is required."]);
      setSectionState("connector", { status: "error", detail: "Provide a connector ID and try again." });
      return;
    }
    if (utf8ByteLength(connectorDefinition) > MAX_CONNECTOR_DEFINITION_BYTES) {
      setConnectorErrors(["The OpenAPI definition exceeds the 1 MB connector import limit."]);
      setSectionState("connector", { status: "error", detail: "The OpenAPI definition is too large." });
      return;
    }
    let definition: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(connectorDefinition);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("The OpenAPI definition must be a JSON object.");
      }
      definition = parsed as Record<string, unknown>;
    } catch (error) {
      setConnectorErrors([error instanceof Error ? error.message : "The OpenAPI definition must be valid JSON."]);
      setSectionState("connector", { status: "error", detail: "Correct the definition and try again." });
      return;
    }
    setConnectorAction(action);
    setConnectorErrors([]);
    setConnectorArtifact(null);
    setSectionState("connector", { status: "loading" });
    try {
      if (action === "validate") {
        const result = await apiFetch<ConsultantConnectorValidationResult>("/consultant/connectors/openapi/validate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ connector_id: client, definition }),
        });
        setConnectorArtifact(result.connector);
      } else {
        const result = await apiFetch<ConsultantConnectorArtifact>("/consultant/connectors/openapi/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ connector_id: client, definition }),
        });
        setConnectorArtifact(result);
      }
      setSectionState("connector", { status: "ready" });
    } catch (error) {
      setConnectorErrors([error instanceof ApiRequestError ? apiRequestReason(error) : error instanceof Error ? error.message : "The connector could not be prepared."]);
      setSectionState("connector", sectionStateForError(error, clientScopeIds, isMspAdmin));
    } finally {
      setConnectorAction(null);
    }
  }

  function downloadConnectorArtifact() {
    if (!connectorArtifact) return;
    const blob = new Blob([JSON.stringify(connectorArtifact, null, 2)], { type: "application/json" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${connectorArtifact.connector_id}-connector.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  }

  function sendToSolutionDelivery() {
    const artifacts = collectHandoffArtifacts(powerAppsArtifact, flowPlan);
    if (artifacts.length === 0) {
      setMessage("Build a Power Apps artifact or prepare a Power Automate plan before sending it to Solution delivery.");
      return;
    }
    const clientIds = Array.from(new Set(
      artifacts
        .map((artifact) => artifact.client_id)
        .filter((clientId): clientId is string => typeof clientId === "string" && clientId.trim().length > 0),
    ));
    if (clientIds.length > 1) {
      setMessage("Build or prepare artifacts for one tenant before sending them to Solution delivery.");
      return;
    }
    const clientId = clientIds[0] ?? currentClientId();
    if (!clientId) {
      setMessage("A tenant scope is required before sending artifacts to Solution delivery.");
      return;
    }
    navigate(SOLUTION_DELIVERY_ROUTE, {
      state: { source: "solutions-architect", clientId, artifacts },
    });
  }

  async function runEmployeeOnboardingDemo() {
    const clientId = resolveClientId(selected?.client_id, scopedClientId, selectedClientId, discoveryClientId || blueprints[0]?.client_id);
    if (!selected || !clientId || !employeeOnboardingEntityId.trim()) {
      setMessage("Select a saved blueprint and provide an existing tenant-scoped ticket before running the local walkthrough.");
      return;
    }
    setEmployeeOnboardingLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<ConsultantEmployeeOnboardingDemo>("/consultant/demos/employee-onboarding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          blueprint_id: selected.id,
          entity_id: employeeOnboardingEntityId.trim(),
        }),
      });
      setEmployeeOnboardingDemo(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to run the local employee-onboarding walkthrough.");
    } finally {
      setEmployeeOnboardingLoading(false);
    }
  }

  const selected = blueprints.find((blueprint) => blueprint.id === selectedId);
  const workflowComponents = architecture?.components.filter((component) => component.kind === "workflow") ?? [];

  function currentClientId() {
    return selected?.client_id?.trim() || scopedClientId.trim() || selectedClientId?.trim() || discoveryClientId.trim() || blueprints[0]?.client_id?.trim() || "";
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Solutions Architect</h2>
            <p className="screen-note consultant-page-intro">This page bundles related but distinct tools for designing and reviewing automation solutions — read each section's heading before acting.</p>
          </div>
        </div>
      </section>

      <div className="consultant-group">
        <div className="consultant-group-heading">
          <h2>Solution blueprints</h2>
          <p className="consultant-group-note">Saved solution plans for this tenant. Create a new one from Solution discovery below, or select an existing one to review or continue its architecture and delivery review.</p>
        </div>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Solutions Architect blueprints</h2>
              <p className="screen-note"><Compass size={16} aria-hidden="true" /> Design and review local solution plans.</p>
            </div>
            <button className="icon-button" type="button" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw size={16} aria-hidden="true" /> Refresh
            </button>
          </div>
          {message ? <div className="notice danger" role="alert"><AlertTriangle size={16} aria-hidden="true" />{message}</div> : null}
          {playbookNotice ? <div className="notice success" role="status">{playbookNotice} <Link to="/playbooks">Playbooks</Link></div> : null}
          <SectionLoadNotice section="blueprints" state={sectionStates.blueprints} onRetry={() => void loadBlueprints()} />
          {sectionStates.blueprints.status === "loading" && blueprints.length === 0 ? <p className="screen-note">Loading solution blueprints…</p> : null}
          {sectionStates.blueprints.status !== "loading" && sectionStates.blueprints.status !== "gated" && sectionStates.blueprints.status !== "error" && blueprints.length === 0 ? (
            <>
              <p className="screen-note">No solution blueprints are available for this tenant.</p>
              <p>No solution blueprints yet. Create one: run <a href="#solution-discovery">Solution discovery below</a>, then Promote the result to a blueprint.</p>
            </>
          ) : blueprints.length > 0 ? (
            <div className="consultant-blueprint-list">
              {blueprints.map((blueprint) => (
                <button
                  className={`consultant-blueprint ${selectedId === blueprint.id ? "selected" : ""}`}
                  key={blueprint.id}
                  type="button"
                  onClick={() => void inspectBlueprint(blueprint.id)}
                >
                  <strong>{blueprint.solution.name}</strong>
                  <span>Tenant {blueprint.client_id} · Risk {blueprint.risk}</span>
                  <em>{blueprint.agents.length} agents · {blueprint.workflows.length} workflows</em>
                </button>
              ))}
            </div>
          ) : null}
          <p className="screen-note">Looking for packaging, deployment, or rollback? See{" "}<Link to="/consultant/solution-delivery">Solution delivery</Link> — a separate review-only screen.</p>
        </section>

        {selected ? (
          <section className="panel" aria-labelledby="blueprint-detail-heading">
            <div className="panel-heading">
              <div>
                <h2 id="blueprint-detail-heading">Blueprint detail</h2>
                <p className="screen-note">The saved blueprint record is the source artifact for the review chain.</p>
              </div>
              {blueprintDetail ? <StatusChip status="completed" /> : null}
            </div>
            <SectionLoadNotice section="blueprintDetail" state={sectionStates.blueprintDetail} onRetry={() => void inspectBlueprint(selected.id)} />
            {sectionStates.blueprintDetail.status === "loading" ? <p className="screen-note">Loading blueprint detail…</p> : null}
            {sectionStates.blueprintDetail.status === "empty" ? <p className="screen-note">Blueprint detail is not available yet.</p> : null}
            {blueprintDetail ? <BlueprintDetailView blueprint={blueprintDetail} /> : null}
          </section>
        ) : null}
      </div>

      <div className="consultant-group">
        <div className="consultant-group-heading">
          <h2>Blueprint walkthrough</h2>
          <p className="consultant-group-note">A bounded local demo that runs the selected blueprint through discovery, architecture, supervisor execution, evaluation, governance, delivery, and audit end-to-end using local fixtures only — no live system is touched.</p>
        </div>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Blueprint walkthrough</h2>
              <p className="screen-note">Run the selected blueprint through discovery, architecture, supervisor execution, evaluation, governance, delivery, and audit.</p>
            </div>
            {employeeOnboardingDemo ? <StatusChip status="completed" /> : null}
          </div>
          <div className="notice">
            <strong>Local fixture only.</strong>{" "}
            No external connector or deployment call is started. The walkthrough generates only local review manifests and a non-deployable package. It requires an existing tenant-scoped ticket and never seeds one. You can start without a ticket in Solution discovery or blueprints.
          </div>
          <div className="grid">
            <label>
              Existing ticket or entity ID
              <input
                value={employeeOnboardingEntityId}
                onChange={(event) => setEmployeeOnboardingEntityId(event.target.value)}
                placeholder="TCK-1001"
              />
            </label>
          </div>
          <button type="button" onClick={() => void runEmployeeOnboardingDemo()} disabled={!canWrite || employeeOnboardingLoading || !selected}>
            {employeeOnboardingLoading ? "Running blueprint walkthrough…" : "Run blueprint walkthrough"}
          </button>
          {!selected ? <p className="screen-note">Select a saved blueprint above before running the walkthrough.</p> : null}
          {!canWrite ? <p className="screen-note">Technician access is required to run the local fixture.</p> : null}
          {employeeOnboardingDemo ? (
            <div className="notice">
              <strong>{employeeOnboardingDemo.stages.blueprint.solution_name} completed in {employeeOnboardingDemo.mode} mode.</strong>{" "}
              Supervisor: {employeeOnboardingDemo.stages.supervisor.status}. Evaluation: {employeeOnboardingDemo.stages.evaluation.production_readiness}. Governance: {employeeOnboardingDemo.stages.governance.status}. Delivery: {employeeOnboardingDemo.stages.delivery.production_readiness}. Artifacts: {employeeOnboardingDemo.stages.artifacts.items.length} review-only.
              <br />{employeeOnboardingDemo.audit.agent_run_count} local agent runs · {employeeOnboardingDemo.audit.audit_event_count} audit events · live provider execution: {employeeOnboardingDemo.boundaries.live_provider_execution ? "started" : "not started"} · deployable package: {employeeOnboardingDemo.boundaries.deployable_package_generated ? "generated" : "not generated"}.
            </div>
          ) : null}
          {employeeOnboardingDemo?.stages.artifacts.delivery_bundle ? (
            <div className="panel-subsection" aria-label="Solutions Architect delivery handoff">
              <div className="panel-heading">
                <div>
                  <h3>Delivery handoff</h3>
                  <p className="screen-note">A deterministic, redacted review bundle is ready for operator handoff.</p>
                </div>
                <StatusChip status="evidence_partial" />
              </div>
              <p>
                <strong>Review-only.</strong> {employeeOnboardingDemo.stages.artifacts.delivery_bundle.manifest.files.length} files · {employeeOnboardingDemo.stages.artifacts.delivery_bundle.manifest.deployment_targets.join(", ")} · deployable: {employeeOnboardingDemo.stages.artifacts.delivery_bundle.manifest.deployable ? "yes" : "no"}.
              </p>
              {employeeOnboardingDemo.stages.artifacts.delivery_bundle_digest ? (
                <p className="screen-note">Bundle digest: <code>{employeeOnboardingDemo.stages.artifacts.delivery_bundle_digest}</code></p>
              ) : null}
              <details>
                <summary>Review bundle files and open items</summary>
                <ul>
                  {employeeOnboardingDemo.stages.artifacts.delivery_bundle.manifest.files.map((file) => (
                    <li key={file.path}><code>{file.path}</code> · {file.digest}</li>
                  ))}
                </ul>
                <p><strong>Still required before any deployment:</strong></p>
                <ul>
                  {employeeOnboardingDemo.stages.artifacts.delivery_bundle.manifest.open_items.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </details>
            </div>
          ) : null}
        </section>
      </div>

      <div className="consultant-group">
        <div className="consultant-group-heading">
          <h2>Design a new solution</h2>
          <p className="consultant-group-note">Capture explicit requirements for a brand-new automation from scratch, then promote the result into a saved blueprint above.</p>
        </div>
        <section className="panel" id="solution-discovery">
        <div className="panel-heading">
          <div>
            <h2>Solution discovery</h2>
            <p className="screen-note">Capture explicit requirements before architecture review. Missing answers stay visible.</p>
          </div>
          {discoveryResult ? <StatusChip status={discoveryResult.readiness === "ready_for_architecture" ? "completed" : "evidence_partial"} /> : null}
        </div>
        <form className="draft-form" onSubmit={(event) => void assessDiscovery(event)}>
          <div className="grid">
            <ClientIdSelect
              label="Customer workspace ID"
              value={discoveryClientId || selected?.client_id || scopedClientId || selectedClientId || blueprints[0]?.client_id || ""}
              onChange={setDiscoveryClientId}
              clients={clients}
              required
              allowFreeform
              id="discovery-client-id"
            />
            <label>
              Solution name
              <input
                value={discoverySolutionName}
                onChange={(event) => setDiscoverySolutionName(event.target.value)}
                placeholder="Employee onboarding"
              />
            </label>
            <label>
              Risk review
              <select value={discoveryRisk} onChange={(event) => setDiscoveryRisk(event.target.value as "low" | "medium" | "high")}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label>
              Business goal
              <textarea rows={2} value={discoveryGoal} onChange={(event) => setDiscoveryGoal(event.target.value)} placeholder="Reduce manual onboarding work" />
            </label>
            <label>
              Users or owners
              <input value={discoveryUsers} onChange={(event) => setDiscoveryUsers(event.target.value)} placeholder="HR, IT" />
            </label>
            <label>
              Systems
              <input value={discoverySystems} onChange={(event) => setDiscoverySystems(event.target.value)} placeholder="Entra, Teams" />
            </label>
            <label>
              Knowledge sources
              <input value={discoveryKnowledge} onChange={(event) => setDiscoveryKnowledge(event.target.value)} placeholder="SharePoint HR policies" />
            </label>
            <label>
              Allowed changes
              <input value={discoveryChanges} onChange={(event) => setDiscoveryChanges(event.target.value)} placeholder="Create user, assign license" />
            </label>
            <label>
              Required approvals
              <input value={discoveryApprovals} onChange={(event) => setDiscoveryApprovals(event.target.value)} placeholder="Assign license" />
            </label>
            <label>
              Failure handling
              <input value={discoveryFailure} onChange={(event) => setDiscoveryFailure(event.target.value)} placeholder="Pause for review" />
            </label>
            <label>
              Data location
              <input value={discoveryDataLocation} onChange={(event) => setDiscoveryDataLocation(event.target.value)} placeholder="Tenant SharePoint" />
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={discoveryLeavesTenant} onChange={(event) => setDiscoveryLeavesTenant(event.target.checked)} />
              Information may leave the tenant
            </label>
          </div>
          <button type="submit" disabled={!canWrite || discoveryLoading || !discoveryGoal.trim()}>
            {discoveryLoading ? "Assessing…" : "Assess discovery"}
          </button>
          {!canWrite ? <p className="screen-note">Technician access is required to submit discovery evidence.</p> : null}
        </form>
        {discoveryResult ? (
          <div className="notice">
            <strong>{discoveryResult.readiness === "ready_for_architecture" ? "Ready for architecture review." : "More discovery is required."}</strong>{" "}
            {discoveryResult.missing_required.length ? `Missing: ${discoveryResult.missing_required.join(", ")}. ` : "All required answers are present. "}
            Risk review: {discoveryResult.risk_review.level}. ROI estimate: {discoveryResult.roi_analysis.status}.
            {discoveryResult.readiness === "ready_for_architecture" ? (
              <div>
                <button type="button" onClick={() => void promoteDiscovery()} disabled={!canWrite || promotionLoading || !discoverySolutionName.trim()}>
                  {promotionLoading ? "Saving blueprint…" : "Save solution blueprint"}
                </button>
                <p className="screen-note">The selected risk is recorded explicitly; no agent, connector, or provider deployment starts.</p>
              </div>
            ) : null}
          </div>
        ) : null}
        <SectionLoadNotice section="discoverySessions" state={sectionStates.discoverySessions} onRetry={() => void loadDiscoverySessions()} />
        {sectionStates.discoverySessions.status === "loading" && discoverySessions.length === 0 ? <p className="screen-note">Loading saved guided discovery sessions…</p> : null}
        {sectionStates.discoverySessions.status === "empty" ? <p className="screen-note">No saved guided discovery sessions yet.</p> : null}
        <div className="notice">
          <strong>Guided discovery</strong>{" "}
          <span>Answer one bounded evidence question at a time. The assistant records your answers and does not infer missing requirements.</span>
          {discoverySessions.length ? (
            <div className="discovery-session-list" aria-label="Saved guided discovery sessions">
              <p className="screen-note">Saved sessions are visible only to this tenant and operator.</p>
              {discoverySessions.map((session) => (
                <button
                  key={session.session_id}
                  type="button"
                  className={discoverySession?.session_id === session.session_id ? "selected" : ""}
                  onClick={() => void resumeGuidedDiscovery(session.session_id)}
                  disabled={guidedLoading}
                >
                  {String(session.answered?.solution_name || session.answered?.business_goal || session.session_id)}
                  {" · "}{session.session_status === "completed" ? "completed" : "active"}
                  {session.updated_at ? ` · ${new Date(session.updated_at).toLocaleString()}` : ""}
                </button>
              ))}
            </div>
          ) : null}
          {!discoverySession ? (
            <div>
              <button type="button" onClick={() => void startGuidedDiscovery()} disabled={!canWrite || guidedLoading || !discoveryGoal.trim()}>
                {guidedLoading ? "Starting…" : "Start guided discovery"}
              </button>
            </div>
          ) : discoverySession.next_question ? (
            <div className="draft-form">
              <button type="button" onClick={startNewGuidedDiscovery} disabled={guidedLoading}>Start new session</button>
              {discoverySession.transcript.length ? (
                <ol aria-label="Guided discovery transcript">
                  {discoverySession.transcript.map((entry, index) => (
                    <li key={`${entry.field ?? entry.role}-${index}`}>
                      <strong>{entry.role === "user" ? "You" : "WAIT"}:</strong> {String(entry.content)}
                    </li>
                  ))}
                </ol>
              ) : null}
              <p><strong>{discoverySession.assistant_message}</strong></p>
              {discoverySession.next_question.kind === "boolean" ? (
                <label className="checkbox-label">
                  <input type="checkbox" checked={guidedBooleanAnswer} onChange={(event) => setGuidedBooleanAnswer(event.target.checked)} />
                  Yes
                </label>
              ) : (
                <label>
                  Your answer
                  <input aria-label="Guided discovery answer" value={guidedAnswer} onChange={(event) => setGuidedAnswer(event.target.value)} placeholder={discoverySession.next_question.kind === "list" ? "Use commas for separate items" : "Enter explicit evidence"} />
                </label>
              )}
              <button type="button" onClick={() => void answerGuidedDiscovery()} disabled={!canWrite || guidedLoading}>
                {guidedLoading ? "Saving…" : "Save answer and continue"}
              </button>
              <p className="screen-note">{discoverySession.unanswered?.length ?? 0} evidence questions remain unanswered.</p>
            </div>
          ) : (
            <div>
              <button type="button" onClick={startNewGuidedDiscovery} disabled={guidedLoading}>Start new session</button>
              {discoverySession.transcript.length ? (
                <ol aria-label="Guided discovery transcript">
                  {discoverySession.transcript.map((entry, index) => (
                    <li key={`${entry.field ?? entry.role}-${index}`}>
                      <strong>{entry.role === "user" ? "You" : "WAIT"}:</strong> {String(entry.content)}
                    </li>
                  ))}
                </ol>
              ) : null}
              <p>Guided discovery is complete. Review the evidence and readiness result above.</p>
            </div>
          )}
        </div>
        </section>
      </div>

      <div className="consultant-group">
        <div className="consultant-group-heading">
          <h2>Reference: Solutions Architect use cases</h2>
          <p className="consultant-group-note">Read-only reference for common Microsoft automation patterns — these entries cannot be edited here. To build your own, use Solution discovery above instead.</p>
        </div>
        <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Solutions Architect use cases</h2>
            <p className="screen-note">Read-only reference for common Microsoft automation patterns — these entries cannot be edited here. To build your own, use Solution discovery above instead.</p>
          </div>
          {monitoring ? <StatusChip status={monitoring.failed_runs ? "needs_review" : "completed"} /> : null}
        </div>
        <SectionLoadNotice section="monitoring" state={sectionStates.monitoring} onRetry={() => void loadMonitoring()} />
        {sectionStates.monitoring.status === "loading" && !monitoring ? <p className="screen-note">Loading agent monitoring…</p> : null}
        {sectionStates.monitoring.status === "empty" ? <p className="screen-note">No agent monitoring data is available yet.</p> : null}
        {monitoring ? (
          <div className="flag-grid">
            <span><strong>{monitoring.agent_count}</strong><br />Agents in scope</span>
            <span><strong>{monitoring.total_runs}</strong><br />Observed runs</span>
            <span><strong>{monitoring.failed_runs}</strong><br />Failed runs</span>
          </div>
        ) : null}
        <SectionLoadNotice section="useCases" state={sectionStates.useCases} onRetry={() => void loadUseCases()} />
        {sectionStates.useCases.status === "loading" && useCases.length === 0 ? <p className="screen-note">Loading Solutions Architect use cases…</p> : null}
        {useCases.length > 0 ? (
          <div className="consultant-component-list">
            {useCases.map((useCase) => <UseCaseCard useCase={useCase} key={useCase.id} />)}
          </div>
        ) : sectionStates.useCases.status !== "loading" && sectionStates.useCases.status !== "gated" && sectionStates.useCases.status !== "error" ? <p>No Solutions Architect use cases are available.</p> : null}
        </section>
      </div>

      <div className="consultant-group">
        <div className="consultant-group-heading">
          <h2>Power Apps builder</h2>
          <p className="consultant-group-note">Build a review-only app handoff from an editable local template.</p>
        </div>
        <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Power Apps builder</h2>
            <p className="screen-note">Generate a local Dataverse and Canvas app handoff for review. No Microsoft write or deployment starts.</p>
            <p>This is an independent tool with its own editable template below — it does not change based on the blueprint selected above, and its defaults (app name, tables, screens, actions) are a starting point you can replace for any project.</p>
          </div>
          {powerAppsArtifact ? <StatusChip status="completed" /> : null}
        </div>
        <form className="draft-form" onSubmit={(event) => void buildPowerAppsArtifact(event)}>
          <label>
            App name
            <input aria-label="Power Apps app name" value={powerAppsName} onChange={(event) => setPowerAppsName(event.target.value)} />
          </label>
          <div className="grid">
            <label>
              Dataverse tables (JSON)
              <textarea rows={8} value={powerAppsEntities} onChange={(event) => setPowerAppsEntities(event.target.value)} />
            </label>
            <label>
              Canvas screens (JSON)
              <textarea rows={8} value={powerAppsScreens} onChange={(event) => setPowerAppsScreens(event.target.value)} />
            </label>
            <label>
              Connector actions (JSON)
              <textarea rows={8} value={powerAppsActions} onChange={(event) => setPowerAppsActions(event.target.value)} />
            </label>
          </div>
          <button type="submit" disabled={!canWrite || powerAppsLoading || !powerAppsName.trim()}>
            {powerAppsLoading ? "Building artifact…" : "Build local artifact"}
          </button>
          {!canWrite ? <p className="screen-note">Technician access is required to build an artifact.</p> : null}
        </form>
        {powerAppsArtifact ? (
          <div className="notice">
            <strong>Power Apps artifact ready for review.</strong>{" "}
            {powerAppsArtifact.files.length} files · {powerAppsArtifact.requires_approval ? "approval required for writes" : "read-only actions"}.
            <br />Credentials, Dataverse writes, execution, and deployment were not started.
          </div>
        ) : null}
        </section>
      </div>

      <div className="consultant-group">
        <div className="consultant-group-heading">
          <h2>Architecture, evaluation &amp; delivery</h2>
          <p className="consultant-group-note">Once a blueprint is selected: confirm environment readiness, load its architecture, then run governance, evaluation, and a review-only delivery plan.</p>
        </div>

        <section className="panel" aria-labelledby="environment-discovery-heading">
          <div className="panel-heading">
            <div>
              <h2 id="environment-discovery-heading">Environment discovery</h2>
              <p className="screen-note">Check the configured connector boundaries before architecture and delivery review.</p>
            </div>
            {environmentResult ? <StatusChip status={environmentResult.readiness} /> : null}
          </div>
          <div className="notice">
            <strong>{writeHealth?.status === "blocked" ? "Safe Mode is active." : "Read-only probe."}</strong>{" "}
            This checks configured connector health only; it does not write to an external system or deploy anything.
          </div>
          <button type="button" onClick={() => void probeEnvironment()} disabled={!canWrite || sectionStates.environment.status === "loading" || !currentClientId()}>
            {sectionStates.environment.status === "loading" ? "Probing environment…" : "Probe environment"}
          </button>
          {!currentClientId() ? <p className="screen-note">Select a blueprint or provide a tenant scope in Solution discovery first.</p> : null}
          {!canWrite ? <p className="screen-note">Technician access is required to probe environment evidence.</p> : null}
          <SectionLoadNotice section="environment" state={sectionStates.environment} onRetry={() => void probeEnvironment()} />
          {sectionStates.environment.status === "empty" && environmentResult === null && selected ? <p className="screen-note">Probe the environment to collect connector evidence for this blueprint.</p> : null}
          {environmentResult ? <EnvironmentEvidence result={environmentResult} /> : null}
        </section>

      {selected && architecture ? (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>{selected.solution.name}</h2>
              <p className="screen-note">Existing runtime mapping only; no execution or deployment is started.</p>
              <p className="screen-note">Acting on: {selected.solution.name} (tenant {selected.client_id}).</p>
            </div>
            <StatusChip status={architecture.readiness === "ready" ? "completed" : "evidence_partial"} />
          </div>
          <div className="row-actions">
            <button type="button" onClick={() => void generatePlaybook()} disabled={!canWrite || playbookLoading}>
              {playbookLoading ? "Generating…" : "Generate Playbook"}
            </button>
          </div>
          <div className="flag-grid">
            <span><strong>{architecture.components.filter((item) => item.kind === "agent").length}</strong><br />Agent components</span>
            <span><strong>{workflowComponents.length}</strong><br />Workflow components</span>
            <span><strong>{architecture.open_items.length}</strong><br />Open review items</span>
          </div>
          {workflowComponents.length > 0 ? (
            <div className="panel-subsection">
              <h3>Workflow designer</h3>
              <p className="screen-note">Edit a bounded local draft before preparing the Power Automate review artifact. Changes are not persisted or executed.</p>
              <div className="workflow-graph-list">
                {workflowComponents.map((workflow) => (
                  <div key={workflow.id}>
                    <WorkflowGraph
                      component={workflow}
                      draft={workflowDrafts[workflow.id]}
                      editable={canWrite}
                      onChange={(draft) => updateWorkflowDraft(workflow.id, draft)}
                    />
                    <button
                      type="button"
                      className="icon-button"
                      onClick={() => void preparePowerAutomatePlan(workflow)}
                      disabled={!canWrite || flowLoading || !(workflowDrafts[workflow.id]?.steps.length)}
                    >
                      {flowLoading ? "Preparing plan…" : "Prepare Power Automate plan"}
                    </button>
                  </div>
                ))}
              </div>
              {!canWrite ? <p className="screen-note">Technician access is required to prepare an export plan.</p> : null}
              {flowPlan ? (
                <div className="notice">
                  <strong>Power Automate plan ready for review.</strong>{" "}
                  {flowPlan.power_automate.actions.length} actions · {flowPlan.requires_approval ? "approval required" : "read-only steps"}.
                  <br />No credentials, execution, or deployment was started.
                </div>
              ) : null}
            </div>
          ) : null}
          {architecture.supervisor && architecture.supervisor.children.length > 1 ? (
            <div className="panel-subsection">
              <h3>Supervisor delegation</h3>
              <p className="screen-note">Children run through the approval-gated agent engine against the selected ticket — nothing bypasses review.</p>
              <div className="notice">
                The delegation is tenant-scoped and one layer deep. Plan it first to verify the dependency order and each child&apos;s tools; running requires an existing ticket ID.
              </div>
              <div className="supervisor-controls">
                <label>
                  Delegation task
                  <textarea rows={2} value={supervisorTask} onChange={(event) => setSupervisorTask(event.target.value)} placeholder="Describe the bounded work for the child agents" />
                </label>
                <div className="grid">
                  <label>
                    Existing ticket or entity ID
                    <input value={supervisorEntityId} onChange={(event) => setSupervisorEntityId(event.target.value)} placeholder="TCK-1001" />
                  </label>
                  <label>
                    Max retries per child
                    <input type="number" min="0" max="3" step="1" value={supervisorMaxRetries} onChange={(event) => setSupervisorMaxRetries(event.target.value)} />
                  </label>
                </div>
                <div className="row-actions">
                  <button type="button" onClick={() => void planSupervisorDelegation()} disabled={!canWrite || supervisorAction !== null}>
                    {supervisorAction === "plan" ? "Planning delegation…" : "Plan delegation"}
                  </button>
                  <button type="button" onClick={() => void runSupervisorDelegation()} disabled={!canWrite || supervisorAction !== null || !supervisorPlan}>
                    {supervisorAction === "run" ? "Running delegation…" : supervisorRun?.status === "pending_approval" ? "Continue delegation" : "Run delegation"}
                  </button>
                  {supervisorRun?.resumption.pending_run_id != null ? (
                    <button type="button" className="secondary-button" onClick={() => void runSupervisorDelegation("cancel")} disabled={!canWrite || supervisorAction !== null}>
                      {supervisorAction === "cancel" ? "Cancelling child…" : `Cancel pending child #${supervisorRun.resumption.pending_run_id}`}
                    </button>
                  ) : null}
                  {supervisorRun?.status === "failed" ? (
                    <button type="button" className="secondary-button" onClick={() => void runSupervisorDelegation("retry")} disabled={!canWrite || supervisorAction !== null}>
                      {supervisorAction === "retry" ? "Retrying delegation…" : "Retry failed children"}
                    </button>
                  ) : null}
                </div>
                {!canWrite ? <p className="screen-note">Technician access is required to plan or run a delegation.</p> : null}
              </div>
              {sectionStates.supervisor.status === "loading" ? <p className="screen-note" aria-busy="true">Updating supervisor delegation…</p> : null}
              <SectionLoadNotice
                section="supervisor"
                state={sectionStates.supervisor}
                onRetry={() => void (supervisorPlan
                  ? runSupervisorDelegation(supervisorRun?.status === "failed" ? "retry" : "run")
                  : planSupervisorDelegation())}
              />
              {supervisorPlan ? <SupervisorPlanView plan={supervisorPlan} /> : null}
              {supervisorRun ? <SupervisorRunView run={supervisorRun} /> : null}
            </div>
          ) : null}
          {architecture.decisions?.length ? <ArchitectureDecisions architecture={architecture} /> : null}
          <div className="panel-subsection">
            <h3>Implementation mapping</h3>
            <div className="consultant-component-list">
              {architecture.components.map((component) => (
                <div className="consultant-component" key={`${component.kind}:${component.id}`}>
                  <div>
                    <strong>{component.name ?? component.id}</strong>
                    <span>{component.kind} · {component.implementation ?? "review required"}</span>
                  </div>
                  <StatusChip status={component.status === "ready" ? "completed" : "evidence_partial"} />
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : selected ? (
        <section className="panel">
          <p>Load {selected.solution.name}'s architecture to see its implementation mapping, workflow designer drafts, and supervisor delegation.</p>
          <p className="screen-note">Acting on: {selected.solution.name} (tenant {selected.client_id}).</p>
          <div className="row-actions">
            <button type="button" onClick={() => void inspectBlueprint(selected.id)}>Load architecture</button>
            <button type="button" onClick={() => void generatePlaybook()} disabled={!canWrite || playbookLoading}>
              {playbookLoading ? "Generating…" : "Generate Playbook"}
            </button>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Solution delivery handoff</h2>
            <p className="screen-note">Carry reviewed Power Apps and Power Automate artifacts into the delivery package.</p>
          </div>
        </div>
        <div className="row-actions">
          <button type="button" onClick={sendToSolutionDelivery} disabled={!powerAppsArtifact && !flowPlan}>
            Send to Solution delivery
          </button>
          <Link className="inline-link" to={SOLUTION_DELIVERY_ROUTE}>Open Solution delivery</Link>
        </div>
        <p className="screen-note">{collectHandoffArtifacts(powerAppsArtifact, flowPlan).length} artifact(s) ready for handoff.</p>
      </section>

      {selected ? (
        <section className="panel" aria-labelledby="evaluate-ship-heading">
          <div className="panel-heading">
            <div>
              <h2 id="evaluate-ship-heading">Evaluate &amp; ship</h2>
              <p className="screen-note">Move the selected blueprint through governance, agent evaluation, and a review-only delivery plan.</p>
            </div>
            {deliveryResult ? <StatusChip status={deliveryResult.production_readiness} /> : null}
          </div>
          {!architecture ? <p className="screen-note">Load the selected blueprint's architecture above to start this chain.</p> : null}
          {architecture ? (
            <div className="consultant-chain">
              <article className="consultant-chain-card">
                <div className="panel-heading">
                  <div>
                    <h3>1. Governance evaluate</h3>
                    <p className="screen-note">Review architecture boundaries and optional connector artifacts for credentials, permissions, and approval requirements.</p>
                  </div>
                  {governanceResult ? <StatusChip status={governanceResult.status} /> : null}
                </div>
                <form className="draft-form" onSubmit={(event) => void evaluateGovernance(event)}>
                  <label>
                    Connector artifacts (JSON)
                    <textarea rows={4} value={governanceArtifacts} onChange={(event) => setGovernanceArtifacts(event.target.value)} />
                  </label>
                  <button type="submit" disabled={!canWrite || sectionStates.governance.status === "loading"}>
                    {sectionStates.governance.status === "loading" ? "Evaluating governance…" : "Evaluate governance"}
                  </button>
                  {!canWrite ? <p className="screen-note">Technician access is required to evaluate governance.</p> : null}
                </form>
                <SectionLoadNotice section="governance" state={sectionStates.governance} onRetry={() => void evaluateGovernance()} />
                {sectionStates.governance.status === "empty" ? <p className="screen-note">No governance review is available yet. Submit the governance form to create one.</p> : null}
                {governanceResult ? (
                  <ReviewChecklist title="Governance checklist" checks={governanceResult.policy_mapping.map((item) => ({ label: item.policy_id, value: item.status }))} />
                ) : null}
                {governanceResult ? <p className="screen-note">{governanceResult.findings.length} finding{governanceResult.findings.length === 1 ? "" : "s"} recorded · high {governanceResult.finding_counts.high} · medium {governanceResult.finding_counts.medium}.</p> : null}
              </article>

              <article className="consultant-chain-card">
                <div className="panel-heading">
                  <div>
                    <h3>2. Agent evaluations</h3>
                    <p className="screen-note">Contract mode checks recorded observations. Controlled execution is available only in demo mode with Safe Mode writes disabled.</p>
                  </div>
                  {evaluationResult ? <StatusChip status={evaluationResult.production_readiness} /> : null}
                </div>
                <form className="draft-form" onSubmit={(event) => void runEvaluation(event)}>
                  <div className="grid">
                    <label>
                      Evaluation mode
                      <select value={evaluationMode} onChange={(event) => setEvaluationMode(event.target.value as "contract" | "controlled")}>
                        <option value="contract">Contract review (no execution)</option>
                        <option value="controlled" disabled={!(authState === "demo" && writeHealth?.status === "blocked")}>Controlled local execution (demo + Safe Mode only)</option>
                      </select>
                    </label>
                    <label>
                      Case ID
                      <input value={evaluationCaseId} onChange={(event) => setEvaluationCaseId(event.target.value)} />
                    </label>
                    <label>
                      Expected tools
                      <input value={evaluationExpectedTools} onChange={(event) => setEvaluationExpectedTools(event.target.value)} placeholder="tool-id, another-tool" />
                    </label>
                    <label>
                      Expected approval tools
                      <input value={evaluationExpectedApprovals} onChange={(event) => setEvaluationExpectedApprovals(event.target.value)} placeholder="tool-id" />
                    </label>
                    <label>
                      Observed tools
                      <input value={evaluationObservedTools} onChange={(event) => setEvaluationObservedTools(event.target.value)} placeholder="tool-id, another-tool" />
                    </label>
                    <label>
                      Observed approval tools
                      <input value={evaluationObservedApprovals} onChange={(event) => setEvaluationObservedApprovals(event.target.value)} placeholder="tool-id" />
                    </label>
                  </div>
                  {evaluationMode === "controlled" ? (
                    <div className="grid">
                      <label>
                        Evaluation agent ID
                        <input value={evaluationAgentId} onChange={(event) => setEvaluationAgentId(event.target.value)} placeholder="agent-id" required />
                      </label>
                      <label>
                        Entity ID
                        <input value={evaluationEntityId} onChange={(event) => setEvaluationEntityId(event.target.value)} required />
                      </label>
                    </div>
                  ) : null}
                  <button type="submit" disabled={!canWrite || sectionStates.evaluations.status === "loading"}>
                    {sectionStates.evaluations.status === "loading" ? "Running evaluation…" : "Run agent evaluation"}
                  </button>
                  {!canWrite ? <p className="screen-note">Technician access is required to run an evaluation.</p> : null}
                </form>
                <SectionLoadNotice section="evaluations" state={sectionStates.evaluations} onRetry={() => void runEvaluation()} />
                {sectionStates.evaluations.status === "empty" ? <p className="screen-note">No agent evaluation is available yet. Run the contract review to create one.</p> : null}
                {evaluationResult ? (
                  <ReviewChecklist
                    title="Evaluation checklist"
                    checks={Object.entries(evaluationResult.dimensions).map(([label, value]) => ({ label, value: String(value) + "%" }))}
                  />
                ) : null}
                {evaluationResult ? <p className="screen-note">{evaluationResult.case_count} case{evaluationResult.case_count === 1 ? "" : "s"} · {evaluationResult.execution_mode === "controlled" ? "controlled local execution recorded" : "observation contract only"} · execution started: {evaluationResult.execution_started ? "yes" : "no"}.</p> : null}
              </article>

              <article className="consultant-chain-card">
                <div className="panel-heading">
                  <div>
                    <h3>3. Delivery plan</h3>
                    <p className="screen-note">The selected architecture, governance result, and evaluation result are included automatically.</p>
                  </div>
                  {deliveryResult ? <StatusChip status={deliveryResult.production_readiness} /> : null}
                </div>
                <form className="draft-form" onSubmit={(event) => void buildDeliveryPlan(event)}>
                  <label>
                    Deployment targets
                    <input value={deliveryTargets} onChange={(event) => setDeliveryTargets(event.target.value)} placeholder="Teams, Power Automate" />
                  </label>
                  <button type="submit" disabled={!canWrite || sectionStates.deliveryPlan.status === "loading" || !governanceResult || !evaluationResult}>
                    {sectionStates.deliveryPlan.status === "loading" ? "Building delivery plan…" : "Build delivery plan"}
                  </button>
                  {!governanceResult || !evaluationResult ? <p className="screen-note">Complete the governance and evaluation cards before building the delivery plan.</p> : null}
                </form>
                <SectionLoadNotice section="deliveryPlan" state={sectionStates.deliveryPlan} onRetry={() => void buildDeliveryPlan()} />
                {sectionStates.deliveryPlan.status === "empty" ? <p className="screen-note">No delivery plan is available yet. Complete the two upstream reviews first.</p> : null}
                {deliveryResult ? (
                  <>
                    <div className="notice">
                      <strong>{deliveryResult.production_readiness === "pass" ? "Ready for review." : "More review is required."}</strong>{" "}
                      {deliveryResult.delivery_bundle_status} handoff · deployment approval required: {deliveryResult.production_deployment_requires_approval ? "yes" : "no"} · execution started: {deliveryResult.execution_started ? "yes" : "no"}.
                    </div>
                    <ReviewChecklist title="Delivery checklist" checks={Object.entries(deliveryResult.checks).map(([label, value]) => ({ label, value: value ? "pass" : "needs review" }))} />
                    <p className="screen-note">Targets: {deliveryResult.deployment_targets.join(", ")}. The package remains review-only and is not a deployable solution.</p>
                  </>
                ) : null}
              </article>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="panel" aria-labelledby="copilot-studio-heading">
        <div className="panel-heading">
          <div>
            <h2 id="copilot-studio-heading">Copilot Studio planner</h2>
            <p className="screen-note">Shape a bounded Copilot Studio handoff from explicit topics, knowledge sources, and connector actions.</p>
          </div>
          {copilotPlan ? <StatusChip status="review_only" /> : null}
        </div>
        <div className="notice">
          <strong>Review-only planning.</strong> This records a proposed artifact; it does not provision Copilot Studio, acquire credentials, execute actions, or publish a channel.
        </div>
        <form className="draft-form" onSubmit={(event) => void buildCopilotStudioPlan(event)}>
          <div className="grid">
            <label>
              Agent name
              <input maxLength={240} value={copilotName} onChange={(event) => setCopilotName(event.target.value)} />
            </label>
            <label>
              Agent description
              <input maxLength={500} value={copilotBusinessGoal} onChange={(event) => setCopilotBusinessGoal(event.target.value)} />
            </label>
          </div>

          <div className="consultant-builder-group">
            <div className="builder-group-heading">
              <div>
                <h3>Topics</h3>
                <p className="screen-note">Up to {MAX_COPILOT_TOPICS}; each topic supports up to {MAX_COPILOT_TRIGGERS} trigger phrases.</p>
              </div>
              <button type="button" className="secondary-button" onClick={addCopilotTopic} disabled={!canWrite || copilotTopics.length >= MAX_COPILOT_TOPICS}>Add topic</button>
            </div>
            <div className="consultant-builder-list">
              {copilotTopics.map((topic, index) => (
                <div className="consultant-builder-row" key={`topic-${index}`}>
                  <label>
                    Topic {index + 1} name
                    <input maxLength={240} aria-label={`Topic ${index + 1} name`} value={topic.name} onChange={(event) => updateCopilotTopic(index, { name: event.target.value })} />
                  </label>
                  <div className="chip-editor">
                    <label htmlFor={`topic-trigger-${index}`}>Trigger phrases</label>
                    <div className="chip-list" aria-label={`Topic ${index + 1} trigger phrases`}>
                      {topic.triggerPhrases.map((phrase) => (
                        <span className="input-chip" key={phrase}>
                          {phrase}
                          <button type="button" aria-label={`Remove trigger phrase ${phrase}`} onClick={() => updateCopilotTopic(index, { triggerPhrases: topic.triggerPhrases.filter((item) => item !== phrase) })}>×</button>
                        </span>
                      ))}
                    </div>
                    <div className="chip-input-row">
                      <input id={`topic-trigger-${index}`} maxLength={240} aria-label={`New trigger phrase for topic ${index + 1}`} value={topic.triggerInput} onChange={(event) => updateCopilotTopic(index, { triggerInput: event.target.value })} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addCopilotTrigger(index); } }} placeholder="Type a phrase" />
                      <button type="button" className="secondary-button" onClick={() => addCopilotTrigger(index)} disabled={!canWrite || !topic.triggerInput.trim() || topic.triggerPhrases.length >= MAX_COPILOT_TRIGGERS}>Add phrase</button>
                    </div>
                  </div>
                  <button type="button" className="secondary-button builder-remove" onClick={() => removeCopilotTopic(index)} disabled={!canWrite}>Remove topic</button>
                </div>
              ))}
            </div>
          </div>

          <div className="consultant-builder-group">
            <div className="builder-group-heading">
              <div>
                <h3>Knowledge sources</h3>
                <p className="screen-note">Knowledge sources are recorded as names only; grounding is proposed in the artifact-generation proposal.</p>
              </div>
              <button type="button" className="secondary-button" onClick={() => setCopilotKnowledgeSources((current) => [...current, ""])} disabled={!canWrite || copilotKnowledgeSources.length >= MAX_COPILOT_KNOWLEDGE_SOURCES}>Add source</button>
            </div>
            <div className="consultant-builder-list">
              {copilotKnowledgeSources.map((source, index) => (
                <div className="chip-input-row" key={`knowledge-${index}`}>
                  <input maxLength={240} aria-label={`Knowledge source ${index + 1}`} value={source} onChange={(event) => setCopilotKnowledgeSources((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} placeholder="Source name" />
                  <button type="button" className="secondary-button" onClick={() => setCopilotKnowledgeSources((current) => current.filter((_, itemIndex) => itemIndex !== index))} disabled={!canWrite}>Remove</button>
                </div>
              ))}
            </div>
          </div>

          <div className="consultant-builder-group">
            <div className="builder-group-heading">
              <div>
                <h3>Connector actions</h3>
                <p className="screen-note">Write methods are always marked as approval-required by the accepted planner contract.</p>
              </div>
              <button type="button" className="secondary-button" onClick={addCopilotAction} disabled={!canWrite || copilotActions.length >= MAX_COPILOT_ACTIONS}>Add action</button>
            </div>
            <div className="consultant-builder-list">
              {copilotActions.map((action, index) => (
                <div className="consultant-builder-row" key={`action-${index}`}>
                  <label>
                    Action ID
                    <input maxLength={64} aria-label={`Action ${index + 1} ID`} value={action.id} onChange={(event) => updateCopilotAction(index, { id: event.target.value })} placeholder="lookup_customer" />
                  </label>
                  <label>
                    Connector ID
                    <input maxLength={64} aria-label={`Action ${index + 1} connector ID`} value={action.connectorId} onChange={(event) => updateCopilotAction(index, { connectorId: event.target.value })} placeholder="customer_api" />
                  </label>
                  <label>
                    Method
                    <select aria-label={`Action ${index + 1} method`} value={action.method} onChange={(event) => updateCopilotAction(index, { method: event.target.value, approvalRequired: event.target.value === "GET" ? action.approvalRequired : true })}>
                      {["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => <option key={method} value={method}>{method}</option>)}
                    </select>
                  </label>
                  <label className="checkbox-label">
                    <input type="checkbox" checked={action.approvalRequired || action.method !== "GET"} disabled={action.method !== "GET"} onChange={(event) => updateCopilotAction(index, { approvalRequired: event.target.checked })} />
                    Approval required
                  </label>
                  <button type="button" className="secondary-button builder-remove" onClick={() => removeCopilotAction(index)} disabled={!canWrite}>Remove action</button>
                </div>
              ))}
            </div>
          </div>

          <button type="submit" disabled={!canWrite || copilotLoading}>
            {copilotLoading ? "Building plan…" : "Build Copilot Studio plan"}
          </button>
          {!canWrite ? <p className="screen-note">Technician access is required to build a planner artifact.</p> : null}
        </form>
        {sectionStates.copilotStudio.status === "loading" ? <p className="screen-note" aria-busy="true">Building the Copilot Studio plan…</p> : null}
        <SectionLoadNotice section="copilotStudio" state={sectionStates.copilotStudio} onRetry={() => void buildCopilotStudioPlan()} />
        {sectionStates.copilotStudio.status === "empty" && !copilotPlan ? <p className="screen-note">No Copilot Studio plan has been generated yet.</p> : null}
        {copilotPlan ? <CopilotStudioPlanView plan={copilotPlan} /> : null}
      </section>

      <section className="panel" aria-labelledby="custom-connector-heading">
        <div className="panel-heading">
          <div>
            <h2 id="custom-connector-heading">Custom connector</h2>
            <p className="screen-note">Validate or prepare a metadata-only Power Platform custom connector from an OpenAPI 2.0 definition.</p>
          </div>
          {connectorArtifact ? <StatusChip status="review_only" /> : null}
        </div>
        <div className="notice">
          <strong>Credential-free review artifact.</strong> Definitions must use HTTPS. The pasted OpenAPI JSON is limited to 1 MB; WAIT does not call the described API, invoke PAC, or deploy a connector.
        </div>
        <div className="draft-form">
          <label>
            Connector ID
            <input maxLength={64} value={connectorId} onChange={(event) => setConnectorId(event.target.value)} placeholder="customer-api" />
          </label>
          <label>
            OpenAPI 2.0 definition (JSON)
            <textarea rows={16} aria-describedby="connector-definition-help" value={connectorDefinition} onChange={(event) => setConnectorDefinition(event.target.value)} />
          </label>
          <p id="connector-definition-help" className="screen-note">{utf8ByteLength(connectorDefinition).toLocaleString()} / 1,000,000 bytes</p>
          <div className="row-actions">
            <button type="button" onClick={() => void runConnectorAction("validate")} disabled={!canWrite || connectorAction !== null}>
              {connectorAction === "validate" ? "Validating…" : "Validate definition"}
            </button>
            <button type="button" className="secondary-button" onClick={() => void runConnectorAction("generate")} disabled={!canWrite || connectorAction !== null}>
              {connectorAction === "generate" ? "Generating…" : "Generate metadata"}
            </button>
          </div>
          {!canWrite ? <p className="screen-note">Technician access is required to validate or generate a connector artifact.</p> : null}
        </div>
        {sectionStates.connector.status === "loading" ? <p className="screen-note" aria-busy="true">{connectorAction === "generate" ? "Generating connector metadata…" : "Validating connector definition…"}</p> : null}
        {sectionStates.connector.status === "gated" ? <SectionLoadNotice section="connector" state={sectionStates.connector} onRetry={() => void runConnectorAction(connectorLastAction)} /> : null}
        {sectionStates.connector.status === "error" && connectorErrors.length > 0 ? (
          <div className="notice danger" role="alert">
            <strong>Connector validation needs attention.</strong>
            <ul className="connector-error-list">{connectorErrors.map((error, index) => <li key={`${error}-${index}`}>{error}</li>)}</ul>
            <button type="button" onClick={() => void runConnectorAction(connectorLastAction)}>Retry {connectorLastAction}</button>
          </div>
        ) : null}
        {sectionStates.connector.status === "error" && connectorErrors.length === 0 ? <SectionLoadNotice section="connector" state={sectionStates.connector} onRetry={() => void runConnectorAction(connectorLastAction)} /> : null}
        {sectionStates.connector.status === "empty" && !connectorArtifact ? <p className="screen-note">Validate a definition to inspect its connector metadata.</p> : null}
        {connectorArtifact ? <ConnectorArtifactView artifact={connectorArtifact} onDownload={downloadConnectorArtifact} /> : null}
      </section>
      </div>
    </div>
  );
}

function CopilotStudioPlanView({ plan }: { plan: ConsultantCopilotStudioPlan }) {
  return (
    <div className="consultant-artifact" aria-label="Copilot Studio plan result">
      <div className="notice success consultant-review-only" role="status">
        <strong>Copilot Studio plan is review-only.</strong> The result declares the following boundaries exactly:
        <div className="artifact-flags">
          <code>generation_status: {plan.generation_status}</code>
          <code>execution_started: {String(plan.execution_started)}</code>
          <code>deployment_started: {String(plan.deployment_started)}</code>
        </div>
      </div>
      <div className="flag-grid">
        <span><strong>{plan.copilot.name}</strong><br />Agent name</span>
        <span><strong>{plan.topics.length}</strong><br />Topics</span>
        <span><strong>{plan.actions.length}</strong><br />Connector actions</span>
      </div>
      <p><strong>Description:</strong> {plan.copilot.business_goal}</p>
      <div className="grid consultant-artifact-grid">
        <div>
          <h3>Topics</h3>
          {plan.topics.length ? (
            <div className="table-scroll">
              <table className="consultant-artifact-table">
                <thead><tr><th scope="col">Topic</th><th scope="col">Trigger phrases</th></tr></thead>
                <tbody>{plan.topics.map((topic) => <tr key={topic.id}><th scope="row">{topic.name}<code>{topic.id}</code></th><td>{topic.trigger_phrases.length ? topic.trigger_phrases.join(", ") : "None recorded"}</td></tr>)}</tbody>
              </table>
            </div>
          ) : <p className="screen-note">No topics recorded.</p>}
        </div>
        <div>
          <h3>Knowledge sources</h3>
          {plan.knowledge_sources.length ? <ul>{plan.knowledge_sources.map((source) => <li key={source}>{source}</li>)}</ul> : <p className="screen-note">No knowledge sources recorded.</p>}
        </div>
      </div>
      <div className="panel-subsection">
        <h3>Connector actions</h3>
        {plan.actions.length ? (
          <div className="table-scroll">
            <table className="consultant-artifact-table">
              <thead><tr><th scope="col">Action</th><th scope="col">Connector</th><th scope="col">Method</th><th scope="col">Approval</th></tr></thead>
              <tbody>{plan.actions.map((action) => <tr key={action.id}><th scope="row">{action.id}</th><td>{action.connector_id}</td><td>{action.method}</td><td>{action.approval_required ? "Required" : "Not required"}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <p className="screen-note">No connector actions recorded.</p>}
      </div>
      <div className="consultant-open-items">
        <h3>Open items</h3>
        <ul>{plan.open_items.map((item) => <li key={item}><input type="checkbox" disabled aria-label={`Open item: ${item}`} />{item}</li>)}</ul>
      </div>
    </div>
  );
}

function ConnectorArtifactView({ artifact, onDownload }: { artifact: ConsultantConnectorArtifact; onDownload: () => void }) {
  return (
    <div className="consultant-artifact" aria-label="Custom connector metadata result">
      <div className="notice success consultant-review-only" role="status">
        <strong>Connector metadata is ready for review.</strong> Credentials are not included and deployment has not started.
      </div>
      <div className="flag-grid">
        <span><strong>{artifact.host}</strong><br />Host</span>
        <span><strong>{artifact.actions.length}</strong><br />Operations</span>
        <span><strong>{artifact.authentication.length}</strong><br />Security definitions</span>
      </div>
      <dl className="consultant-detail-grid">
        <div><dt>Connector ID</dt><dd>{artifact.connector_id}</dd></div>
        <div><dt>Display name</dt><dd>{artifact.display_name}</dd></div>
        <div><dt>API version</dt><dd>{artifact.api_version}</dd></div>
        <div><dt>Base path</dt><dd>{artifact.base_path}</dd></div>
      </dl>
      <div className="grid consultant-artifact-grid">
        <div>
          <h3>Operations</h3>
          <div className="table-scroll">
            <table className="consultant-artifact-table">
              <thead><tr><th scope="col">Operation</th><th scope="col">Method</th><th scope="col">Path</th><th scope="col">Responses</th></tr></thead>
              <tbody>{artifact.actions.map((action) => <tr key={action.id}><th scope="row">{action.id}<span>{action.summary}</span></th><td>{action.method}</td><td><code>{action.path}</code></td><td>{action.response_statuses.join(", ")}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
        <div>
          <h3>Security definitions</h3>
          {artifact.authentication.length ? <ul>{artifact.authentication.map((definition) => <li key={definition.name}><strong>{definition.name}</strong> · {definition.type}{definition.in ? ` · ${definition.in}` : ""}</li>)}</ul> : <p className="screen-note">None recorded.</p>}
        </div>
      </div>
      <button type="button" onClick={onDownload}>Download connector JSON</button>
    </div>
  );
}

function SupervisorPlanView({ plan }: { plan: ConsultantSupervisorPlan }) {
  const childrenById = new Map(plan.supervisor.children.map((child) => [child.id, child]));
  return (
    <div className="supervisor-result" aria-label="Supervisor delegation plan">
      <div className="panel-heading">
        <div>
          <h4>Delegation plan ready</h4>
          <p className="screen-note">Dependency order is verified before any child run starts. Supervisor depth: {plan.supervisor.max_depth}; recursion: {plan.supervisor.recursion}.</p>
        </div>
        <StatusChip status={plan.execution_started ? "running" : "available"} />
      </div>
      <div className="supervisor-plan-list">
        {plan.assignments.map((assignment) => {
          const child = childrenById.get(assignment.child_agent_id);
          return (
            <article className="consultant-component" key={`${assignment.sequence}:${assignment.child_agent_id}`}>
              <div>
                <strong>{assignment.sequence}. {child?.name ?? assignment.child_agent_id}</strong>
                <span>Agent {assignment.child_agent_id} · tools: {child?.tool_ids.join(", ") || "none recorded"}</span>
                <span>Depends on: {child?.depends_on_agent_ids.join(", ") || "none"}</span>
              </div>
              <StatusChip status={child?.enabled === false ? "failed" : "available"} hint={child?.context_policy} />
            </article>
          );
        })}
      </div>
    </div>
  );
}

function SupervisorRunView({ run }: { run: ConsultantSupervisorRun }) {
  return (
    <div className="supervisor-result" aria-label="Supervisor delegation results">
      <div className="panel-heading">
        <div>
          <h4>Delegation {run.status}</h4>
          <p className="screen-note">
            {run.execution_started ? "Child execution was recorded by the agent engine." : "No child execution was recorded."}{" "}
            {run.approval_requests_created ? "At least one child is waiting for approval." : "No approval request was created."}
          </p>
        </div>
        <StatusChip status={run.status} />
      </div>
      <div className="supervisor-plan-list">
        {run.children.map((child) => (
          <article className="consultant-component" key={`${child.agent_id}:${child.sequence}`}>
            <div>
              <strong>{child.sequence}. {child.agent_id}</strong>
              <span>Run {child.run_id != null ? `#${child.run_id}` : "not created"} · attempt {child.attempt ?? 1}{child.retry_count ? ` · ${child.retry_count} ${child.retry_count === 1 ? "retry" : "retries"}` : ""}</span>
              {child.error_detail ? <span>{child.error_detail}</span> : null}
              {child.approval_id != null ? <span>Approval request #{child.approval_id} is required before this child can continue.</span> : null}
              {child.run_id != null ? <Link to="/executions">Follow up in Activity</Link> : null}
            </div>
            <StatusChip status={child.status} />
          </article>
        ))}
      </div>
      {run.resumption.pending_run_id != null ? <p className="screen-note">Approval-paused child run #{run.resumption.pending_run_id} must be approved or cancelled before later children are delegated.</p> : null}
      {run.cancellation.applied ? <p className="screen-note">The requested child run was cancelled; later children were not delegated.</p> : null}
    </div>
  );
}

function BlueprintDetailView({ blueprint }: { blueprint: ConsultantBlueprint }) {
  return (
    <dl className="consultant-detail-grid">
      <div><dt>Solution</dt><dd>{blueprint.solution.name}</dd></div>
      <div><dt>Tenant</dt><dd>{blueprint.client_id}</dd></div>
      <div><dt>Risk</dt><dd>{blueprint.risk}</dd></div>
      <div><dt>Created by</dt><dd>{blueprint.created_by}</dd></div>
      <div><dt>Agents</dt><dd>{blueprint.agents.length}</dd></div>
      <div><dt>Workflows</dt><dd>{blueprint.workflows.length}</dd></div>
    </dl>
  );
}

function EnvironmentEvidence({ result }: { result: ConsultantEnvironmentResult }) {
  return (
    <div className="consultant-environment">
      <p className="screen-note">
        {result.probe_performed ? "Provider health evidence was returned for eligible configured connectors." : "No provider health response was returned; configuration is not authorization evidence."}
        {" "}{result.systems.length} systems reviewed.
      </p>
      <div className="table-scroll">
        <table className="consultant-environment-table">
          <caption>Environment status matrix</caption>
          <thead>
            <tr><th scope="col">System</th><th scope="col">Status</th><th scope="col">Configured</th><th scope="col">Probe result</th></tr>
          </thead>
          <tbody>
            {result.systems.map((system) => {
              const configured = system.provider_status === "configured" || system.provider_status === "blocked" || system.provider_status === "ready";
              const probe = system.probe?.status === "passed"
                ? "Passed"
                : system.probe?.status === "failed"
                  ? "Failed" + (system.probe.layer !== "unknown" ? " · " + system.probe.layer : "")
                  : "Not run";
              return (
                <tr key={system.id}>
                  <th scope="row">{system.name}</th>
                  <td><StatusChip status={system.status} /></td>
                  <td>{configured ? "Yes" : "No"}</td>
                  <td>{probe}{system.probe?.message ? <span className="screen-note"> · {system.probe.message}</span> : null}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {result.limitations.length ? <p className="screen-note">{result.limitations.length} limitation{result.limitations.length === 1 ? "" : "s"} remain explicit for review.</p> : null}
    </div>
  );
}

function ReviewChecklist({ title, checks }: { title: string; checks: Array<{ label: string; value: string }> }) {
  return (
    <div className="consultant-review-checklist" aria-label={title}>
      <h4>{title}</h4>
      <ul>
        {checks.map((check) => <li key={check.label}><span>{humanizeName(check.label)}</span><StatusChip status={check.value} /></li>)}
      </ul>
    </div>
  );
}

function ArchitectureDecisions({ architecture }: { architecture: ConsultantArchitecture }) {
  const decisions = Array.isArray(architecture.decisions)
    ? architecture.decisions.filter((decision): decision is ArchitectureDecision => Boolean(decision) && typeof decision === "object")
    : [];
  const engine = architecture.decision_engine;
  const decisionCount = typeof engine?.decision_count === "number" ? engine.decision_count : decisions.length;
  const unresolvedCount = typeof engine?.unresolved_decision_count === "number"
    ? engine.unresolved_decision_count
    : decisions.filter((decision) => safeText(decision.status) === "needs_review").length;
  const safeguards = [
    engine?.inference_started === false ? "No inference started" : null,
    engine?.execution_started === false ? "No execution started" : null,
    engine?.deployment_started === false ? "No deployment started" : null,
  ].filter((item): item is string => Boolean(item));

  return (
    <div className="panel-subsection" aria-label="Architecture decisions">
      <div className="panel-heading">
        <div>
          <h3>Architecture decisions</h3>
          <p className="screen-note">
            {decisionCount} decisions · {unresolvedCount} need review · authority: {humanizeName(safeText(engine?.authority) || "not recorded")}
          </p>
        </div>
      </div>
      {safeguards.length ? <p className="screen-note">{safeguards.join(" · ")}.</p> : null}
      <div className="consultant-component-list">
        {decisions.map((decision, index) => <ArchitectureDecisionCard decision={decision} key={safeText(decision.id) || `decision-${index}`} />)}
      </div>
    </div>
  );
}

function ArchitectureDecisionCard({ decision }: { decision: ArchitectureDecision }) {
  const requirements: Array<{ label: string; value: unknown }> = [
    { label: "Required permissions", value: decision.required_permissions },
    { label: "Licenses", value: decision.licenses },
    { label: "Approval", value: decision.approval_requirements },
    { label: "Read/write behavior", value: decision.read_write_behavior },
    { label: "Risk", value: decision.risk },
    { label: "Reversibility", value: decision.reversibility },
    { label: "Execution boundary", value: decision.execution_boundary },
    { label: "Complexity", value: decision.estimated_complexity },
  ];

  return (
    <article className="consultant-component" aria-label={`Architecture decision: ${safeText(decision.capability) || "Unnamed capability"}`}>
      <div>
        <div className="panel-heading">
          <div>
            <strong>{safeText(decision.capability) || "Unnamed capability"}</strong>
            <div className="screen-note">
              <span className="status-chip info">{humanizeDecisionTarget(decision.chosen_target)}</span>
            </div>
          </div>
          <StatusChip status={safeText(decision.status) || undefined} />
        </div>
        <p><strong>Why this was chosen</strong><br />{safeText(decision.why) || "No rationale was recorded."}</p>
        <DecisionValues label="Alternatives considered" values={decision.alternatives_considered} />
        <div className="grid">
          {requirements.map((requirement) => <DecisionRequirement key={requirement.label} {...requirement} />)}
        </div>
        <DecisionValues label="Dependencies" values={decision.dependencies} />
        <DecisionValues label="Open questions" values={decision.open_questions} />
      </div>
    </article>
  );
}

function DecisionRequirement({ label, value }: { label: string; value: unknown }) {
  const values = stringValues(value);
  if (!values.length) return null;
  return <div><strong>{label}</strong><span>{values.map(humanizeName).join(", ")}</span></div>;
}

function DecisionValues({ label, values }: { label: string; values: unknown }) {
  const rendered = stringValues(values);
  if (!rendered.length) return null;
  return <p><strong>{label}</strong><br />{rendered.map(humanizeName).join(", ")}</p>;
}

function stringValues(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value] : [];
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  return typeof value === "number" || typeof value === "boolean" ? [String(value)] : [];
}

function safeText(value: unknown): string {
  return typeof value === "string" ? value : typeof value === "number" || typeof value === "boolean" ? String(value) : "";
}

function humanizeDecisionTarget(value: unknown): string {
  const target = safeText(value).toLowerCase();
  const labels: Record<string, string> = {
    wait_agent: "WAIT Agent",
    wait_workflow: "WAIT Workflow",
    microsoft_graph: "Microsoft Graph",
    unsupported: "Unsupported",
  };
  return labels[target] ?? humanizeName(safeText(value) || "Not recorded");
}

function splitList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function copilotIdentifier(value: string, prefix: string, index: number): string {
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9_.:-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
  const identifier = /^[a-z]/.test(normalized) ? normalized : `${prefix}-${normalized}`;
  return (identifier || `${prefix}-${index + 1}`).slice(0, 64);
}

function uniqueCopilotIdentifiers(values: string[], prefix: string): string[] {
  const used = new Set<string>();
  return values.map((value, index) => {
    const base = copilotIdentifier(value, prefix, index);
    let candidate = base;
    let suffix = 2;
    while (used.has(candidate)) {
      const suffixText = `-${suffix}`;
      candidate = `${base.slice(0, 64 - suffixText.length)}${suffixText}`;
      suffix += 1;
    }
    used.add(candidate);
    return candidate;
  });
}

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function resolveClientId(
  selectedClientId: string | undefined,
  scopedClientId: string,
  enteredClientId: string,
  fallbackClientId: string | undefined,
): string {
  return [selectedClientId, scopedClientId, enteredClientId, fallbackClientId]
    .map((value) => value?.trim() ?? "")
    .find(Boolean) ?? "";
}

function powerAutomateIdentifier(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
}

function parseJsonArray(value: string, label: string): Record<string, unknown>[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error(`${label} must be a JSON array of objects.`);
  }
  return parsed as Record<string, unknown>[];
}

function UseCaseCard({ useCase }: { useCase: ConsultantUseCase }) {
  return (
    <article className="consultant-component">
      <div>
        <strong>{useCase.title}</strong>
        <span>{useCase.category} · {useCase.business_goal}</span>
        <span>Services: {useCase.services.join(", ")}</span>
        <span>Approval boundaries: {useCase.approval_boundaries.join(", ")}</span>
      </div>
    </article>
  );
}

function WorkflowGraph({
  component,
  draft,
  editable,
  onChange,
}: {
  component: ConsultantArchitectureComponent;
  draft?: { trigger: string; steps: string[] };
  editable: boolean;
  onChange: (draft: { trigger: string; steps: string[] }) => void;
}) {
  const current = draft ?? { trigger: component.trigger ?? "", steps: component.steps ?? [] };
  const nodes = [current.trigger || "Trigger", ...current.steps];
  return (
    <article className="workflow-graph">
      <strong>{component.name ?? component.id}</strong>
      {editable ? (
        <div className="workflow-draft-editor">
          <label>
            Trigger
            <input
              value={current.trigger}
              onChange={(event) => onChange({ ...current, trigger: event.target.value })}
            />
          </label>
          {current.steps.map((step, index) => (
            <div className="workflow-step-editor" key={`${component.id}:edit:${index}`}>
              <label>
                Step {index + 1}
                <input
                  value={step}
                  onChange={(event) => {
                    const steps = [...current.steps];
                    steps[index] = event.target.value;
                    onChange({ ...current, steps });
                  }}
                />
              </label>
              <button
                type="button"
                className="icon-button"
                onClick={() => onChange({ ...current, steps: current.steps.filter((_, stepIndex) => stepIndex !== index) })}
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            className="icon-button"
            onClick={() => onChange({ ...current, steps: [...current.steps, "New action"] })}
          >
            Add step
          </button>
        </div>
      ) : null}
      <div className="workflow-graph-nodes">
        {nodes.map((node, index) => (
          <div className="workflow-graph-node" key={`${component.id}:${index}`}>
            <span>{index === 0 ? "Trigger" : `Step ${index}`}</span>
            <strong>{node}</strong>
          </div>
        ))}
      </div>
    </article>
  );
}
