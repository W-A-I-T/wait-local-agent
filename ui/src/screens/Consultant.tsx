import { FormEvent, useCallback, useEffect, useState } from "react";
import { AlertTriangle, Compass, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { useDashboard } from "../app/DashboardContext";
import { ApiRequestError, apiFetch } from "../api/client";
import { StatusChip } from "../components/StatusChip";
import { humanizeName } from "../lib/fields";
import type {
  ArchitectureDecision,
  ConsultantArchitecture,
  ConsultantArchitectureComponent,
  ConsultantBlueprint,
  ConsultantBlueprintPromotionResult,
  ConsultantDiscoveryResult,
  ConsultantDiscoverySession,
  ConsultantEmployeeOnboardingDemo,
  ConsultantMonitoring,
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

type ConsultantSection = "blueprints" | "discoverySessions" | "useCases" | "monitoring";
type SectionLoadStatus = "loading" | "ready" | "empty" | "gated" | "error";
type SectionLoadState = { status: SectionLoadStatus; detail?: string };
type SectionLoadStates = Record<ConsultantSection, SectionLoadState>;

const SECTION_DETAILS: Record<ConsultantSection, { label: string; pack: string; retryLabel: string }> = {
  blueprints: { label: "solution blueprints", pack: "Microsoft Admin", retryLabel: "blueprints" },
  discoverySessions: { label: "guided discovery sessions", pack: "Microsoft Admin", retryLabel: "discovery sessions" },
  useCases: { label: "Solutions Architect use cases", pack: "Microsoft Admin", retryLabel: "use cases" },
  monitoring: { label: "agent monitoring", pack: "Microsoft Admin", retryLabel: "monitoring" },
};

const INITIAL_SECTION_STATES: SectionLoadStates = {
  blueprints: { status: "loading" },
  discoverySessions: { status: "loading" },
  useCases: { status: "loading" },
  monitoring: { status: "loading" },
};

function sectionStateForError(error: unknown): SectionLoadState {
  if (error instanceof ApiRequestError && error.status === 403) {
    return { status: "gated" };
  }
  if (error instanceof ApiRequestError && error.status === 404) {
    return { status: "empty" };
  }
  return {
    status: "error",
    detail: error instanceof Error ? error.message : "The section could not be loaded.",
  };
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
        Requires the {details.pack} pack or Microsoft Admin capability. <Link to="/system/extensions">Open Extensions / Packs</Link>
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
  const { canWrite, clientId: scopedClientId } = useDashboard();
  const [blueprints, setBlueprints] = useState<ConsultantBlueprint[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
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
      setSectionState("blueprints", sectionStateForError(error));
    }
  }, [setSectionState]);

  const loadUseCases = useCallback(async () => {
    setSectionState("useCases", { status: "loading" });
    try {
      const result = await apiFetch<{ use_cases: ConsultantUseCase[] }>("/consultant/use-cases");
      const rows = Array.isArray(result.use_cases) ? result.use_cases : [];
      setUseCases(rows);
      setSectionState("useCases", { status: rows.length ? "ready" : "empty" });
    } catch (error) {
      setSectionState("useCases", sectionStateForError(error));
    }
  }, [setSectionState]);

  const loadMonitoring = useCallback(async () => {
    setSectionState("monitoring", { status: "loading" });
    try {
      const result = await apiFetch<ConsultantMonitoring>("/consultant/monitoring/agents");
      setMonitoring(result);
      setSectionState("monitoring", { status: "ready" });
    } catch (error) {
      setSectionState("monitoring", sectionStateForError(error));
    }
  }, [setSectionState]);

  const loadDiscoverySessions = useCallback(async () => {
    setSectionState("discoverySessions", { status: "loading" });
    try {
      const result = await apiFetch<ConsultantDiscoverySession[]>("/consultant/discovery/sessions");
      const rows = Array.isArray(result) ? result : [];
      setDiscoverySessions(rows);
      setSectionState("discoverySessions", { status: rows.length ? "ready" : "empty" });
    } catch (error) {
      setSectionState("discoverySessions", sectionStateForError(error));
    }
  }, [setSectionState]);

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
    setArchitecture(null);
    setFlowPlan(null);
    setMessage("");
    setPlaybookNotice("");
    try {
      const result = await apiFetch<ConsultantArchitecture>(
        `/consultant/blueprints/${encodeURIComponent(blueprintId)}/architecture`
      );
      setArchitecture(result);
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
    const clientId = resolveClientId(selected?.client_id, scopedClientId, discoveryClientId, blueprints[0]?.client_id);
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

  async function runEmployeeOnboardingDemo() {
    const clientId = resolveClientId(selected?.client_id, scopedClientId, discoveryClientId, blueprints[0]?.client_id);
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
    return selected?.client_id?.trim() || scopedClientId.trim() || discoveryClientId.trim() || blueprints[0]?.client_id?.trim() || "";
  }

  return (
    <div className="screen-stack">
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
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Employee onboarding walkthrough</h2>
            <p className="screen-note">Run the canonical bounded local fixture through discovery, architecture, supervisor execution, evaluation, governance, delivery, and audit.</p>
          </div>
          {employeeOnboardingDemo ? <StatusChip status="completed" /> : null}
        </div>
        <div className="notice">
          <strong>Local fixture only.</strong>{" "}
          No Microsoft, PSA, RMM, documentation, Teams, live-provider, or deployment call is started. The walkthrough generates only local review manifests and a non-deployable package. It requires an existing tenant-scoped ticket and never seeds one. You can start without a ticket in Solution discovery or blueprints.
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
          {employeeOnboardingLoading ? "Running local walkthrough…" : "Run local onboarding walkthrough"}
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
            <label>
              Customer workspace ID
              <input
                value={discoveryClientId || selected?.client_id || scopedClientId || blueprints[0]?.client_id || ""}
                onChange={(event) => setDiscoveryClientId(event.target.value)}
                placeholder="acme"
              />
            </label>
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

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Solutions Architect use cases</h2>
            <p className="screen-note">Review starting points for Microsoft work. These entries are planning guidance only.</p>
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

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Power Apps builder</h2>
            <p className="screen-note">Generate a local Dataverse and Canvas app handoff for review. No Microsoft write or deployment starts.</p>
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

      {selected && architecture ? (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>{selected.solution.name}</h2>
              <p className="screen-note">Existing runtime mapping only; no execution or deployment is started.</p>
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
              <p className="screen-note">Child agents receive bounded tenant-scoped tasks and structured results only.</p>
              <div className="consultant-component-list">
                {architecture.supervisor.children.map((child) => (
                  <div className="consultant-component" key={child.id}>
                    <div>
                      <strong>{child.id}</strong>
                      <span>{child.kind} · {child.context_policy ?? "bounded structured context"}</span>
                    </div>
                    <StatusChip status="evidence_partial" />
                  </div>
                ))}
              </div>
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
          <p>Choose the blueprint to load its architecture view.</p>
          <div className="row-actions">
            <button type="button" onClick={() => void inspectBlueprint(selected.id)}>Load architecture</button>
            <button type="button" onClick={() => void generatePlaybook()} disabled={!canWrite || playbookLoading}>
              {playbookLoading ? "Generating…" : "Generate Playbook"}
            </button>
          </div>
        </section>
      ) : null}
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
      <StatusChip status="evidence_partial" />
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
