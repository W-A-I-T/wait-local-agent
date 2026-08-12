import { FormEvent, useCallback, useEffect, useState } from "react";
import { AlertTriangle, Compass, RefreshCw } from "lucide-react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { StatusChip } from "../components/StatusChip";
import type {
  ConsultantArchitecture,
  ConsultantArchitectureComponent,
  ConsultantBlueprint,
  ConsultantBlueprintPromotionResult,
  ConsultantDiscoveryResult,
  ConsultantDiscoverySession,
  ConsultantMonitoring,
  ConsultantUseCase,
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

export function Consultant() {
  const { canWrite, clientId: scopedClientId } = useDashboard();
  const [blueprints, setBlueprints] = useState<ConsultantBlueprint[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [architecture, setArchitecture] = useState<ConsultantArchitecture | null>(null);
  const [workflowDrafts, setWorkflowDrafts] = useState<Record<string, { trigger: string; steps: string[] }>>({});
  const [useCases, setUseCases] = useState<ConsultantUseCase[]>([]);
  const [monitoring, setMonitoring] = useState<ConsultantMonitoring | null>(null);
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
  const [guidedAnswer, setGuidedAnswer] = useState("");
  const [guidedBooleanAnswer, setGuidedBooleanAnswer] = useState(false);
  const [guidedLoading, setGuidedLoading] = useState(false);
  const [promotionLoading, setPromotionLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [rows, catalog, health] = await Promise.all([
        apiFetch<ConsultantBlueprint[]>("/consultant/blueprints"),
        apiFetch<{ use_cases: ConsultantUseCase[] }>("/consultant/use-cases"),
        apiFetch<ConsultantMonitoring>("/consultant/monitoring/agents"),
      ]);
      setBlueprints(rows);
      setUseCases(catalog.use_cases);
      setMonitoring(health);
      if (selectedId && rows.some((row) => row.id === selectedId)) return;
      setSelectedId(rows[0]?.id ?? null);
      setArchitecture(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load consultant blueprints.");
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function inspectBlueprint(blueprintId: string) {
    setSelectedId(blueprintId);
    setArchitecture(null);
    setFlowPlan(null);
    setMessage("");
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
    const clientId = selected?.client_id ?? scopedClientId ?? (discoveryClientId.trim() || blueprints[0]?.client_id);
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
    const clientId = selected?.client_id ?? scopedClientId ?? (discoveryClientId.trim() || blueprints[0]?.client_id);
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
    const clientId = selected?.client_id ?? scopedClientId ?? (discoveryClientId.trim() || blueprints[0]?.client_id);
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

  async function promoteDiscovery() {
    const clientId = selected?.client_id ?? (discoveryClientId.trim() || blueprints[0]?.client_id);
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
    const clientId = selected?.client_id ?? scopedClientId ?? blueprints[0]?.client_id;
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

  const selected = blueprints.find((blueprint) => blueprint.id === selectedId);
  const workflowComponents = architecture?.components.filter((component) => component.kind === "workflow") ?? [];

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Consultant blueprints</h2>
            <p className="screen-note"><Compass size={16} aria-hidden="true" /> Design and review local solution plans.</p>
          </div>
          <button className="icon-button" type="button" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw size={16} aria-hidden="true" /> Refresh
          </button>
        </div>
        {message ? <div className="notice danger" role="alert"><AlertTriangle size={16} aria-hidden="true" />{message}</div> : null}
        {blueprints.length === 0 ? <p>No solution blueprints are available for this tenant.</p> : (
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
        )}
      </section>

      <section className="panel">
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
                value={discoveryClientId || selected?.client_id || blueprints[0]?.client_id || ""}
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
        <div className="notice">
          <strong>Guided discovery</strong>{" "}
          <span>Answer one bounded evidence question at a time. The assistant records your answers and does not infer missing requirements.</span>
          {!discoverySession ? (
            <div>
              <button type="button" onClick={() => void startGuidedDiscovery()} disabled={!canWrite || guidedLoading || !discoveryGoal.trim()}>
                {guidedLoading ? "Starting…" : "Start guided discovery"}
              </button>
            </div>
          ) : discoverySession.next_question ? (
            <div className="draft-form">
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
            <p>Guided discovery is complete. Review the evidence and readiness result above.</p>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Consultant use cases</h2>
            <p className="screen-note">Review starting points for Microsoft work. These entries are planning guidance only.</p>
          </div>
          {monitoring ? <StatusChip status={monitoring.failed_runs ? "needs_review" : "completed"} /> : null}
        </div>
        {monitoring ? (
          <div className="flag-grid">
            <span><strong>{monitoring.agent_count}</strong><br />Agents in scope</span>
            <span><strong>{monitoring.total_runs}</strong><br />Observed runs</span>
            <span><strong>{monitoring.failed_runs}</strong><br />Failed runs</span>
          </div>
        ) : null}
        {useCases.length > 0 ? (
          <div className="consultant-component-list">
            {useCases.map((useCase) => <UseCaseCard useCase={useCase} key={useCase.id} />)}
          </div>
        ) : <p>No consultant use cases are available.</p>}
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
        <section className="panel"><p>Choose the blueprint to load its architecture view.</p><button type="button" onClick={() => void inspectBlueprint(selected.id)}>Load architecture</button></section>
      ) : null}
    </div>
  );
}

function splitList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
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
