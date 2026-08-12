import { FormEvent, useCallback, useEffect, useState } from "react";
import { AlertTriangle, Compass, RefreshCw } from "lucide-react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { StatusChip } from "../components/StatusChip";
import type {
  ConsultantArchitecture,
  ConsultantArchitectureComponent,
  ConsultantBlueprint,
  ConsultantDiscoveryResult,
  ConsultantMonitoring,
  ConsultantUseCase,
  PowerAutomateFlowPlan,
} from "../api/types";

export function Consultant() {
  const { canWrite } = useDashboard();
  const [blueprints, setBlueprints] = useState<ConsultantBlueprint[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [architecture, setArchitecture] = useState<ConsultantArchitecture | null>(null);
  const [useCases, setUseCases] = useState<ConsultantUseCase[]>([]);
  const [monitoring, setMonitoring] = useState<ConsultantMonitoring | null>(null);
  const [flowPlan, setFlowPlan] = useState<PowerAutomateFlowPlan | null>(null);
  const [flowLoading, setFlowLoading] = useState(false);
  const [discoveryGoal, setDiscoveryGoal] = useState("");
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
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to build the architecture view.");
    }
  }

  async function preparePowerAutomatePlan(workflow: ConsultantArchitectureComponent) {
    if (!selected) return;
    setFlowLoading(true);
    setMessage("");
    try {
      const result = await apiFetch<PowerAutomateFlowPlan>("/consultant/workflows/power-automate/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: selected.client_id,
          workflow_id: workflow.id,
          workflow_name: workflow.name ?? workflow.id,
          trigger: workflow.trigger ?? "Manual review request",
          steps: (workflow.steps ?? []).map((name, index) => ({
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

  async function assessDiscovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clientId = selected?.client_id ?? blueprints[0]?.client_id;
    if (!clientId || !discoveryGoal.trim()) {
      setMessage("Choose a blueprint tenant and provide a business goal before assessing discovery.");
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
          </div>
        ) : null}
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
              <h3>Workflow design</h3>
              <p className="screen-note">Read-only sequence preview from the stored blueprint.</p>
              <div className="workflow-graph-list">
                {workflowComponents.map((workflow) => (
                  <div key={workflow.id}>
                    <WorkflowGraph component={workflow} />
                    <button
                      type="button"
                      className="icon-button"
                      onClick={() => void preparePowerAutomatePlan(workflow)}
                      disabled={!canWrite || flowLoading || !(workflow.steps?.length)}
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

function WorkflowGraph({ component }: { component: ConsultantArchitectureComponent }) {
  const nodes = [component.trigger ?? "Trigger", ...(component.steps ?? [])];
  return (
    <article className="workflow-graph">
      <strong>{component.name ?? component.id}</strong>
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
