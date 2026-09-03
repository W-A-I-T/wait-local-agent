import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiFetchBlob } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { ScopeBadge } from "../components/ScopeBadge";
import type { ExecutionDetail, ExecutionRun } from "../api/types";
import { useDashboard } from "../app/DashboardContext";

function displayValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
}

export function Executions() {
  const { selectedClientId, clients } = useDashboard();
  const [executions, setExecutions] = useState<ExecutionRun[]>([]);
  const [selected, setSelected] = useState<ExecutionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams();
      if (kind) query.set("kind", kind);
      if (status) query.set("status", status);
      const suffix = query.toString() ? `?${query.toString()}` : "";
      setExecutions(await apiFetch<ExecutionRun[]>(`/executions${suffix}`));
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load execution history.");
    } finally {
      setLoading(false);
    }
  }, [kind, selectedClientId, status]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function showDetail(execution: ExecutionRun) {
    setDetailLoading(true);
    try {
      setSelected(await apiFetch<ExecutionDetail>(`/executions/${execution.id}`));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load execution detail.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function downloadArtifact(artifact: ExecutionDetail["artifacts"][number]) {
    if (!selected) return;
    try {
      const blob = await apiFetchBlob(`/executions/${selected.id}/artifacts/${artifact.id}`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = artifact.name;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to download artifact.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h2>Execution History</h2><div><ScopeBadge /> <span>{executions.length} runs</span></div></div>
        <p className="screen-note">Review persisted run status, trigger context, redacted steps, and generated artifact metadata.</p>
        <div className="grid">
          <label>Run kind<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="">All kinds</option><option value="agent">Agent</option><option value="workflow">Workflow</option><option value="smart_action">Smart action</option></select></label>
          <label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="success">Success</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="cancelled">Cancelled</option></select></label>
        </div>
        {message ? <div className="notice" role="alert">{message}</div> : null}
      </section>

      <section className="table-list">
        {loading ? <LoadingState label="Loading execution history…" /> : executions.length === 0 ? <EmptyState title="No execution history" why="Completed, failed, and cancelled runs appear here after an execution starts." /> : executions.map((execution) => <button className="table-row" type="button" key={execution.id} onClick={() => void showDetail(execution)}>
          <div><strong>Run #{execution.id}</strong><span>{execution.run_kind} · {execution.trigger_source}</span></div>
          <div><strong>{execution.status}</strong><span>{execution.actor} · {execution.client_id || "unbound"}</span></div>
          <em>{execution.started_at}</em>
        </button>)}
      </section>

      {detailLoading ? <LoadingState label="Loading execution details…" /> : selected ? <section className="panel">
        <div className="panel-heading"><h2>Run #{selected.id}</h2><span>{selected.status}</span></div>
        <p className="screen-note">{selected.run_kind} · trigger {selected.trigger_source} · actor {selected.actor}</p>
        {Object.keys(selected.metadata ?? {}).length ? <p className="screen-note">Provider metadata: {displayValue(selected.metadata)}</p> : null}
        <h3>Steps</h3>
        {selected.steps.length === 0 ? <p>No steps recorded.</p> : null}
        <div className="stack-list">{selected.steps.map((step) => <article className="panel" key={step.id}>
          <div className="panel-heading"><strong>{step.ordinal + 1}. {step.name}</strong><span>{step.status}</span></div>
          <p className="screen-note">{step.kind}</p>
          <pre>{displayValue(step.output)}</pre>
          {step.error_detail ? <p className="notice danger">{step.error_detail}</p> : null}
        </article>)}</div>
        <h3>Artifacts</h3>
        {selected.artifacts.length === 0 ? <p>No artifacts recorded.</p> : <div className="table-list">{selected.artifacts.map((artifact) => <div className="table-row" key={artifact.id}><div><strong>{artifact.name}</strong><span>{artifact.media_type}</span></div><span>{artifact.byte_size} bytes</span><span>{artifact.sha256}</span><button type="button" className="secondary-button" onClick={() => void downloadArtifact(artifact)}>Download</button></div>)}</div>}
      </section> : null}
    </div>
  );
}
