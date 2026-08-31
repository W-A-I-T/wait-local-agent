import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";

type ActivityItem = {
  activity_id: string;
  kind: string;
  source_run_id: number | null;
  canonical_execution_id: number | null;
  title: string;
  entity_id: string;
  actor: string;
  status: string;
  started_at: string;
  finished_at: string;
  client_id: string | null;
  detail_path: string;
  trigger_source: string;
};

const kindOptions = ["", "workflow", "agent", "smart_action", "collector", "backfill"];

export function ActivityRuns() {
  const [rows, setRows] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (kind) params.set("kinds", kind);
    if (status.trim()) params.set("status", status.trim());
    return params.toString();
  }, [kind, status]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await apiFetch<ActivityItem[]>(`/packs/operator-control/activity/runs?${query}`);
      if (!Array.isArray(result)) throw new Error("The appliance returned invalid activity data.");
      setRows(result);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load unified activity.");
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>All runs</h2>
            <p className="screen-note">One tenant-scoped timeline for canonical executions plus legacy workflow, agent, Smart Action, collector, and backfill runs that are not already represented by an execution record.</p>
          </div>
          <button type="button" onClick={() => void refresh()} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
        <div className="grid">
          <label>Run type<select value={kind} onChange={(event) => setKind(event.target.value)}>
            {kindOptions.map((option) => <option key={option || "all"} value={option}>{option ? option.replace("_", " ") : "All run types"}</option>)}
          </select></label>
          <label>Status<input value={status} onChange={(event) => setStatus(event.target.value)} placeholder="completed" /></label>
        </div>
        {message ? <div className="notice" role="alert">{message}</div> : null}
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Run history</h2><span>{rows.length} shown</span></div>
        {loading ? <LoadingState label="Loading run history…" /> : rows.length === 0 ? <EmptyState title="No matching runs" why="No recorded activity matches the current tenant and filters." /> : (
          <div className="table-list">
            {rows.map((row) => (
              <article className="table-row" key={row.activity_id}>
                <div>
                  <strong>{row.title}</strong>
                  <span>{row.kind.replace("_", " ")} · {row.client_id || "global"}{row.entity_id ? ` · ${row.entity_id}` : ""}</span>
                  <small>{row.started_at || row.finished_at || "timestamp unavailable"}{row.actor ? ` · ${row.actor}` : ""}{row.trigger_source ? ` · ${row.trigger_source}` : ""}</small>
                </div>
                <span>{row.status}</span>
                <div>
                  {row.canonical_execution_id ? <Link to="/executions">Execution #{row.canonical_execution_id}</Link> : <Link to={row.detail_path}>Open source</Link>}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
