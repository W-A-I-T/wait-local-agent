import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch, shouldSuppressClientScopeError } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { SelectClientNotice } from "../components/SelectClientNotice";
import { ScopeBadge } from "../components/ScopeBadge";
import type { AgentBackfill, AgentBackfillPreview, AgentDefinition } from "../api/types";

function parseEntityIds(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))];
}

function scopeAwareErrorMessage(
  error: unknown,
  fallback: string,
  clientScopeIds: string[] | null | undefined,
  isMspAdmin: boolean | undefined
): string {
  if (shouldSuppressClientScopeError(error, clientScopeIds, isMspAdmin)) return "";
  return error instanceof Error ? error.message : fallback;
}

export function Backfills() {
  const { canWrite, selectedClientId = "", clients = [], clientScopeIds, isMspAdmin = false } = useDashboard();
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [backfills, setBackfills] = useState<AgentBackfill[]>([]);
  const [loading, setLoading] = useState(true);
  const hasLoadedRef = useRef(false);
  const [agentId, setAgentId] = useState("");
  const [entityText, setEntityText] = useState("");
  const [inputText, setInputText] = useState("{}");
  const [maxConcurrency, setMaxConcurrency] = useState("1");
  const [preview, setPreview] = useState<AgentBackfillPreview | null>(null);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    if (!hasLoadedRef.current) setLoading(true);
    try {
      const [agentRows, backfillRows] = await Promise.all([
        apiFetch<AgentDefinition[]>("/agents"),
        apiFetch<AgentBackfill[]>("/agent-backfills")
      ]);
      setAgents(agentRows);
      setBackfills(backfillRows);
      if (!agentId && agentRows[0]) setAgentId(agentRows[0].id);
    } catch (error) {
      setMessage(scopeAwareErrorMessage(error, "Unable to load backfills.", clientScopeIds, isMspAdmin));
    } finally {
      hasLoadedRef.current = true;
      setLoading(false);
    }
  }, [agentId, clientScopeIds, isMspAdmin, selectedClientId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function buildPayload() {
    const entityIds = parseEntityIds(entityText);
    if (!agentId || entityIds.length === 0) {
      throw new Error("Choose an agent and provide at least one ticket ID.");
    }
    let input: Record<string, unknown>;
    try {
      input = JSON.parse(inputText) as Record<string, unknown>;
    } catch {
      throw new Error("Input must be valid JSON.");
    }
    if (!input || Array.isArray(input) || typeof input !== "object") {
      throw new Error("Input must be a JSON object.");
    }
    return {
      agent_id: agentId,
      entity_ids: entityIds,
      input,
      max_concurrency: Number(maxConcurrency),
      client_id: selectedClientId.trim() || undefined
    };
  }

  async function previewBackfill() {
    try {
      const result = await apiFetch<AgentBackfillPreview>("/agent-backfills/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload())
      });
      setPreview(result);
      setMessage("Dry run complete. Nothing was persisted or executed.");
    } catch (error) {
      setMessage(scopeAwareErrorMessage(error, "Unable to preview backfill.", clientScopeIds, isMspAdmin));
    }
  }

  async function createBackfill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await apiFetch<AgentBackfill>("/agent-backfills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload())
      });
      setMessage("Backfill queued.");
      setPreview(null);
      await refresh();
    } catch (error) {
      setMessage(scopeAwareErrorMessage(error, "Unable to create backfill.", clientScopeIds, isMspAdmin));
    }
  }

  async function controlBackfill(backfill: AgentBackfill, action: "run" | "pause" | "cancel" | "rerun-failed") {
    try {
      await apiFetch<AgentBackfill>(`/agent-backfills/${backfill.id}/${action}`, { method: "POST" });
      setMessage(`Backfill ${action === "rerun-failed" ? "failed items rerun" : `${action} requested`}.`);
      await refresh();
    } catch (error) {
      setMessage(scopeAwareErrorMessage(error, "Unable to update backfill.", clientScopeIds, isMspAdmin));
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h2>Agent Backfills</h2><span>{backfills.length} runs</span></div>
        <p className="screen-note">Preview a bounded historical run before queueing it. Backfills reuse the normal agent executor and never exceed 100 entities.</p>
        <form id="backfill-form" className="draft-form" onSubmit={createBackfill}>
          <div className="grid">
            <label>Agent<select value={agentId} onChange={(event) => setAgentId(event.target.value)}><option value="">Choose agent</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
            <p className="screen-note">Scope: <ScopeBadge /></p>
            <label>Max concurrency<select value={maxConcurrency} onChange={(event) => setMaxConcurrency(event.target.value)}><option value="1">1 · sequential</option><option value="2">2</option><option value="3">3</option><option value="4">4</option></select></label>
          </div>
          <label>Ticket IDs<textarea rows={5} value={entityText} onChange={(event) => setEntityText(event.target.value)} placeholder="One ticket ID per line" /></label>
          <label>Input JSON<textarea rows={3} value={inputText} onChange={(event) => setInputText(event.target.value)} /></label>
          {!selectedClientId && !isMspAdmin ? <SelectClientNotice /> : null}
          <div className="template-actions"><button type="button" disabled={!canWrite || (!selectedClientId && !isMspAdmin)} title={!canWrite ? "Requires technician access" : !selectedClientId ? "Choose a client in the top bar first" : undefined} onClick={() => void previewBackfill()}>Preview</button><button type="submit" disabled={!canWrite || (!selectedClientId && !isMspAdmin)} title={!canWrite ? "Requires technician access" : !selectedClientId ? "Choose a client in the top bar first" : undefined}>Queue backfill</button></div>
        </form>
        {preview ? <div className="notice">Preview: {preview.entity_count} entities, {preview.execution_mode.replace("_", " ")}, no data persisted.</div> : null}
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>

      <section className="table-list">
        {loading ? <LoadingState label="Loading backfills…" /> : backfills.length === 0 ? <EmptyState title="No backfills yet" why="Backfills appear after you queue a historical agent run from the form above." action={{ label: "Preview a backfill above", to: "#backfill-form" }} /> : backfills.map((backfill) => {
          const terminal = ["completed", "completed_with_errors", "cancelled"].includes(backfill.status);
          return <article className="panel" key={backfill.id}>
            <div className="panel-heading"><h3>Backfill #{backfill.id}</h3><span>{backfill.status}</span></div>
            <p className="screen-note">Agent: {backfill.agent_id} · {backfill.processed_count}/{backfill.entity_ids.length} processed · {backfill.succeeded_count} succeeded · {backfill.failed_count} failed</p>
            <p className="screen-note">Client: {backfill.client_id || "unbound"} · Concurrency: {backfill.max_concurrency}</p>
            {backfill.failed_entity_ids.length ? <p className="screen-note">Failed: {backfill.failed_entity_ids.join(", ")}</p> : null}
            {backfill.error_detail ? <p className="notice danger">{backfill.error_detail}</p> : null}
            <div className="template-actions">
              <button type="button" disabled={!canWrite || terminal} title={!canWrite ? "Requires technician access" : terminal ? "This backfill is complete" : undefined} onClick={() => void controlBackfill(backfill, "run")}>Run / resume</button>
              <button type="button" disabled={!canWrite || backfill.status !== "queued"} title={!canWrite ? "Requires technician access" : backfill.status !== "queued" ? "Only queued backfills can be paused" : undefined} onClick={() => void controlBackfill(backfill, "pause")}>Pause</button>
              <button type="button" disabled={!canWrite || terminal} title={!canWrite ? "Requires technician access" : terminal ? "This backfill is complete" : undefined} onClick={() => void controlBackfill(backfill, "cancel")}>Cancel</button>
              <button type="button" disabled={!canWrite || backfill.failed_entity_ids.length === 0} title={!canWrite ? "Requires technician access" : backfill.failed_entity_ids.length === 0 ? "There are no failed items to rerun" : undefined} onClick={() => void controlBackfill(backfill, "rerun-failed")}>Rerun failed</button>
            </div>
          </article>;
        })}
      </section>
    </div>
  );
}
