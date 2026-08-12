import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Compass, RefreshCw } from "lucide-react";
import { apiFetch } from "../api/client";
import { StatusChip } from "../components/StatusChip";
import type { ConsultantArchitecture, ConsultantArchitectureComponent, ConsultantBlueprint } from "../api/types";

export function Consultant() {
  const [blueprints, setBlueprints] = useState<ConsultantBlueprint[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [architecture, setArchitecture] = useState<ConsultantArchitecture | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiFetch<ConsultantBlueprint[]>("/consultant/blueprints");
      setBlueprints(rows);
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
                {workflowComponents.map((workflow) => <WorkflowGraph component={workflow} key={workflow.id} />)}
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
