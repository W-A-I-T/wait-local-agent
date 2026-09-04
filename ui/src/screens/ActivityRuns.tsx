import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiFetchForClient } from "../api/scopedFetch";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { ScopeBadge } from "../components/ScopeBadge";
import { RunRow, runKindLabel } from "../components/RunRow";
import { useDashboard } from "../app/DashboardContext";

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
  ticket_id?: string | null;
  approval_id?: number | null;
};

const kindOptions = [
  ["", "All"],
  ["workflow", "Workflow"],
  ["playbook", "Playbook"],
  ["agent", "Agent"],
  ["execution", "Execution"],
  ["smart_action", "Smart action"],
  ["scheduled", "Scheduled"],
  ["backfill", "Backfill"]
] as const;

export function ActivityRuns() {
  const { selectedClientId = "" } = useDashboard();
  const [searchParams, setSearchParams] = useSearchParams();
  const [rows, setRows] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState(() => searchParams.get("kind") ?? "");
  const [status, setStatus] = useState("");
  const executionId = parseExecutionId(searchParams.get("execution_id"));

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (kind && kind !== "execution" && kind !== "scheduled") params.set("kinds", kind);
    if (status.trim()) params.set("status", status.trim());
    return params.toString();
  }, [kind, status]);

  const visibleRows = rows.filter((row) => (
    (executionId === null || row.canonical_execution_id === executionId) &&
    (!kind || (
      (kind === "execution" ? row.canonical_execution_id !== null : true)
      && (kind !== "scheduled" || row.trigger_source === "scheduled")
    ))
  ));

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await apiFetchForClient<ActivityItem[]>(selectedClientId, `/packs/operator-control/activity/runs?${query}`);
      if (!Array.isArray(result)) throw new Error("The appliance returned invalid activity data.");
      setRows(result);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load unified activity.");
    } finally {
      setLoading(false);
    }
  }, [query, selectedClientId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function selectKind(nextKind: string) {
    setKind(nextKind);
    const nextParams = new URLSearchParams(searchParams);
    if (nextKind) nextParams.set("kind", nextKind);
    else nextParams.delete("kind");
    setSearchParams(nextParams, { replace: true });
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Runs</h2>
            <p className="screen-note">One client-scoped timeline for workflow, execution, smart action, scheduled, and backfill records.</p>
          </div>
          <div><ScopeBadge /> <button type="button" onClick={() => void refresh()} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></div>
        </div>
        <div className="grid">
          <div className="filter-chips" aria-label="Run record kind">
            <span className="screen-note">Record kind</span>
            {kindOptions.map(([value, label]) => <button key={value || "all"} type="button" className={kind === value ? "selected" : "secondary-button"} aria-pressed={kind === value} onClick={() => selectKind(value)}>{label}</button>)}
          </div>
          <label>Status<input value={status} onChange={(event) => setStatus(event.target.value)} placeholder="completed" /></label>
        </div>
        {message ? <div className="notice" role="alert">{message}</div> : null}
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Run history</h2><span>{visibleRows.length} shown</span></div>
        {loading ? <LoadingState label="Loading run history…" /> : visibleRows.length === 0 ? <EmptyState title="No matching runs" why="No recorded activity matches the current client and filters." /> : (
          <div className="table-list">
            {visibleRows.map((row) => (
              <RunRow
                key={row.activity_id}
                title={row.title}
                kind={row.canonical_execution_id !== null ? "execution" : row.trigger_source === "scheduled" ? "scheduled" : row.kind}
                clientId={row.client_id}
                origin={activityOrigin(row)}
                status={row.status}
                timestamp={row.started_at || row.finished_at}
                href={activityHref(row)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function activityHref(row: ActivityItem): string {
  if (row.canonical_execution_id !== null) {
    return `/executions/${row.canonical_execution_id}?kind=execution`;
  }
  return row.detail_path;
}

function activityOrigin(row: ActivityItem): string | null {
  if (row.approval_id !== null && row.approval_id !== undefined) return `Approval ${row.approval_id}`;
  if (row.canonical_execution_id !== null) {
    return row.source_run_id === null ? "Source run unavailable" : `Source run ${row.source_run_id}`;
  }
  if (row.ticket_id) return `Ticket ${row.ticket_id}`;
  if (row.entity_id) {
    const kind = runKindLabel(row.kind);
    return kind === "Workflow" || kind === "Agent" ? `Ticket ${row.entity_id}` : row.entity_id;
  }
  if (row.source_run_id !== null) return `Source run ${row.source_run_id}`;
  return null;
}

function parseExecutionId(value: string | null): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}
