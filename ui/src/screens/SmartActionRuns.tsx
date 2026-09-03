import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError, apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { RunRow } from "../components/RunRow";
import { StatusChip } from "../components/StatusChip";

type SmartActionRun = {
  id: number;
  action_id: string;
  actor: string;
  status: string;
  payload_digest: string;
  output: unknown;
  evidence: unknown[];
  approval_id: number | null;
  created_at: string;
  updated_at: string;
  client_id: string | null;
  error_detail: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
}

function numberValue(value: unknown): number {
  return typeof value === "number" ? value : Number(value);
}

function normalizeRun(value: unknown): SmartActionRun | null {
  if (!isRecord(value)) return null;
  const id = numberValue(value.id);
  if (!Number.isInteger(id)) return null;
  return {
    id,
    action_id: stringValue(value.action_id),
    actor: stringValue(value.actor),
    status: stringValue(value.status),
    payload_digest: stringValue(value.payload_digest),
    output: value.output,
    evidence: Array.isArray(value.evidence) ? value.evidence : [],
    approval_id: typeof value.approval_id === "number" ? value.approval_id : null,
    created_at: stringValue(value.created_at),
    updated_at: stringValue(value.updated_at),
    client_id: typeof value.client_id === "string" ? value.client_id : null,
    error_detail: stringValue(value.error_detail)
  };
}

function formatDate(value: string): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatJson(value: unknown): string {
  if (value === undefined) return "Not recorded";
  try {
    const rendered = JSON.stringify(value, null, 2);
    return rendered === undefined ? "Not recorded" : rendered;
  } catch {
    return "Unable to render this value.";
  }
}

export function SmartActionRuns() {
  const { selectedClientId } = useDashboard();
  const [runs, setRuns] = useState<SmartActionRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SmartActionRun | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [detailError, setDetailError] = useState("");

  const query = selectedClientId ? `?client_id=${encodeURIComponent(selectedClientId)}` : "";

  const loadRuns = useCallback(() => {
    let cancelled = false;
    setListLoading(true);
    setListError("");
    void apiFetch<unknown>(`/smart-actions/runs${query}`)
      .then((result) => {
        if (cancelled) return;
        const rows = Array.isArray(result) ? result.map(normalizeRun).filter((run): run is SmartActionRun => run !== null) : [];
        setRuns(rows);
        setSelectedRunId(null);
        setDetail(null);
        setDetailError("");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setRuns([]);
        setSelectedRunId(null);
        setDetail(null);
        setDetailError("");
        setListError(error instanceof Error ? error.message : "Unable to load smart action runs.");
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => { cancelled = true; };
  }, [query]);

  useEffect(() => loadRuns(), [loadRuns]);

  useEffect(() => {
    if (selectedRunId === null) return;
    let cancelled = false;
    setDetailLoading(true);
    setDetailError("");
    setDetail(null);
    void apiFetch<unknown>(`/smart-actions/runs/${encodeURIComponent(String(selectedRunId))}${query}`)
      .then((result) => {
        if (cancelled) return;
        const run = normalizeRun(result);
        if (run) setDetail(run);
        else setDetailError("The appliance returned an invalid run detail.");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiRequestError && error.status === 404) {
          setDetailError("This run was not found in the current client scope.");
        } else {
          setDetailError(error instanceof Error ? error.message : "Unable to load run details.");
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => { cancelled = true; };
  }, [query, selectedRunId]);

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Operations</p><h2>Smart Action Runs</h2></div>
          <button type="button" className="secondary-button" onClick={loadRuns}>Refresh</button>
        </div>
        <p className="screen-note">Read-only history of smart actions that have run in the current client scope.</p>
        {listError ? <div className="notice danger" role="alert">{listError}</div> : null}
        {listLoading ? <p className="screen-note" aria-busy="true">Loading smart action runs…</p> : runs.length === 0 ? <div className="empty-state"><h3>No smart action runs yet.</h3></div> : (
          <div className="run-list">
            {runs.map((run) => (
              <RunRow
                key={run.id}
                title={run.action_id || `Run ${run.id}`}
                kind="smart_action"
                clientId={run.client_id}
                origin={smartActionOrigin(run)}
                status={run.status}
                timestamp={formatDate(run.created_at)}
                onOpen={() => setSelectedRunId(run.id)}
              />
            ))}
          </div>
        )}
      </section>

      {selectedRunId !== null ? <section className="panel" aria-labelledby="smart-action-run-detail-heading">
        <div className="panel-heading"><div><p className="eyebrow">Run detail</p><h2 id="smart-action-run-detail-heading">Smart Action Run {selectedRunId}</h2></div>{detail ? <StatusChip status={detail.status} /> : null}</div>
        {detailLoading ? <p className="screen-note" aria-busy="true">Loading run details…</p> : null}
        {detailError ? <div className="notice danger" role="alert">{detailError}</div> : null}
        {detail ? <>
          <dl className="smart-action-detail-grid"><div><dt>Action</dt><dd>{detail.action_id || "Not recorded"}</dd></div><div><dt>Actor</dt><dd>{detail.actor || "Not recorded"}</dd></div><div><dt>Client</dt><dd>{detail.client_id || "All clients"}</dd></div><div><dt>Created</dt><dd>{formatDate(detail.created_at)}</dd></div><div><dt>Updated</dt><dd>{formatDate(detail.updated_at)}</dd></div><div><dt>Approval</dt><dd>{detail.approval_id === null ? "Not recorded" : <Link to="/approvals">Approval {detail.approval_id}</Link>}</dd></div><div><dt>Payload digest</dt><dd><code>{detail.payload_digest || "Not recorded"}</code></dd></div><div><dt>Output</dt><dd><pre className="smart-action-code">{formatJson(detail.output)}</pre></dd></div><div><dt>Evidence</dt><dd><pre className="smart-action-code">{formatJson(detail.evidence)}</pre></dd></div></dl>
          {detail.error_detail ? <div className="notice danger" role="alert">{detail.error_detail}</div> : null}
        </> : null}
      </section> : null}
    </div>
  );
}

function smartActionOrigin(run: SmartActionRun): string {
  const approval = run.approval_id === null ? "Approval unavailable" : `Approval ${run.approval_id}`;
  return `${approval} · ${run.actor || "Actor unavailable"}`;
}
