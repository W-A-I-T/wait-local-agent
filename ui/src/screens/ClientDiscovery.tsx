import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { ClientCandidate, DeploymentMode, DiscoveryResponse } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { LoadingState } from "../components/LoadingState";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

const states = ["all", "proposed", "ambiguous", "unmatched", "conflicting", "verified", "dismissed"] as const;
type FilterState = typeof states[number];

function stateLabel(value: string): string {
  return value === "proposed" ? "Needs confirmation" : value.charAt(0).toUpperCase() + value.slice(1);
}

export function ClientDiscovery() {
  const { role, roleResolved } = useDashboard();
  const [mode, setMode] = useState<DeploymentMode | null>(null);
  const [modeLoading, setModeLoading] = useState(true);
  const [modeBusy, setModeBusy] = useState(false);
  const [filter, setFilter] = useState<FilterState>("all");
  const [data, setData] = useState<DiscoveryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadMode = useCallback(async () => {
    setModeLoading(true);
    try {
      const result = await apiFetch<{ mode: DeploymentMode | null }>("/setup/mode");
      setMode(result.mode);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load deployment mode.");
    } finally {
      setModeLoading(false);
    }
  }, []);

  const loadCandidates = useCallback(async () => {
    if (!roleResolved || role !== "admin" || mode === "smb") return;
    setLoading(true);
    setError("");
    try {
      const query = filter === "all" ? "" : `?match_state=${encodeURIComponent(filter)}`;
      const result = await apiFetch<DiscoveryResponse>(`/discovery/clients${query}`);
      setData(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load client discovery.");
    } finally {
      setLoading(false);
    }
  }, [filter, mode, role, roleResolved]);

  useEffect(() => { void loadMode(); }, [loadMode]);
  useEffect(() => { void loadCandidates(); }, [loadCandidates]);

  const updateMode = async (nextMode: DeploymentMode) => {
    setModeBusy(true);
    setError("");
    try {
      const result = await apiFetch<{ mode: DeploymentMode }>("/setup/mode", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: nextMode })
      });
      setMode(result.mode);
      setNotice(`Workspace mode set to ${result.mode.toUpperCase()}.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to save workspace mode.");
    } finally {
      setModeBusy(false);
    }
  };

  const action = async (candidate: ClientCandidate, operation: "accept" | "create-client" | "dismiss") => {
    setBusyId(candidate.candidate_id);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/discovery/clients/${encodeURIComponent(candidate.candidate_id)}/${operation}`, { method: "POST" });
      setNotice(operation === "accept" ? "Client match accepted." : operation === "create-client" ? "Client created and linked." : "Candidate dismissed.");
      await loadCandidates();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The client discovery action could not be completed.");
    } finally {
      setBusyId(null);
    }
  };

  const acceptProposed = async () => {
    const proposed = (data?.items ?? []).filter((candidate) => candidate.match_state === "proposed");
    if (!proposed.length) return;
    setBusyId("bulk");
    setError("");
    try {
      await apiFetch("/discovery/clients/accept-proposed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_ids: proposed.map((candidate) => candidate.candidate_id) })
      });
      setNotice(`${proposed.length} proposed match${proposed.length === 1 ? "" : "es"} accepted.`);
      await loadCandidates();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Bulk acceptance could not be completed.");
    } finally {
      setBusyId(null);
    }
  };

  const runDiscovery = async () => {
    setBusyId("run");
    setError("");
    try {
      const result = await apiFetch<{ failures: Array<{ detail: string }> }>("/discovery/clients/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      setNotice(result.failures.length ? `Discovery completed with ${result.failures.length} provider issue${result.failures.length === 1 ? "" : "s"}.` : "Discovery completed.");
      await loadCandidates();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Client discovery could not be run.");
    } finally {
      setBusyId(null);
    }
  };

  const summary = data?.summary;
  const visibleItems = useMemo(() => data?.items ?? [], [data]);

  return (
    <RoleGate role={role} resolved={roleResolved} allowed={["admin"]} fallback={<section className="panel" role="alert"><h2>Administrator access required</h2><p className="screen-note">Only administrators can reconcile provider organizations into the client directory.</p></section>}>
      {modeLoading ? <LoadingState label="Loading workspace mode…" /> : mode === "smb" ? (
        <section className="panel"><p className="eyebrow">Directory</p><h2>Client discovery is disabled</h2><p className="screen-note">SMB mode keeps client setup manual. Change the workspace mode below if this appliance serves multiple customers.</p><label>Workspace mode<select value={mode} disabled={modeBusy} onChange={(event) => void updateMode(event.target.value as DeploymentMode)}><option value="smb">SMB</option><option value="msp">MSP</option></select></label></section>
      ) : (
        <div className="screen-stack">
          <section className="panel clients-hero"><div><p className="eyebrow">Directory</p><h2>Client discovery</h2><p className="screen-note">Bring provider organizations into a review queue. WAIT never creates or links a client without an administrator action.</p></div><div className="analytics-filter-actions"><Link className="secondary-button" to="/clients">Back to Clients</Link><button type="button" onClick={() => void runDiscovery()} disabled={busyId !== null}>{busyId === "run" ? "Discovering…" : "Run discovery"}</button></div></section>
          <section className="panel"><div className="panel-heading"><div><h2>Workspace mode</h2><span>First-run setting</span></div><span>{mode ? `${mode.toUpperCase()} mode` : "Not selected"}</span></div><label>Deployment mode<select value={mode ?? ""} disabled={modeBusy} onChange={(event) => event.target.value && void updateMode(event.target.value as DeploymentMode)}><option value="">Choose a mode</option><option value="msp">MSP — reconcile provider organizations</option><option value="smb">SMB — manual client setup</option></select></label></section>
          {summary ? <section className="analytics-summary" aria-label="Discovery summary"><span><strong>{summary.discovered}</strong> discovered</span><span><strong>{summary.reconciled}</strong> reconciled</span><span><strong>{summary.need_confirmation}</strong> need confirmation</span><span><strong>{summary.unmatched}</strong> unmatched</span><span><strong>{summary.conflicts}</strong> conflicts</span></section> : null}
          {notice ? <div className="notice success" role="status">{notice}</div> : null}
          {error ? <div className="notice danger" role="alert">{error}</div> : null}
          <section className="panel"><div className="panel-heading"><div><h2>Review queue</h2><span>Exact matches are suggestions; ambiguous and conflicting rows stay blocked.</span></div><div className="analytics-filter-actions"><label>Filter<select value={filter} onChange={(event) => setFilter(event.target.value as FilterState)}>{states.map((state) => <option key={state} value={state}>{state === "all" ? "All candidates" : stateLabel(state)}</option>)}</select></label><button className="secondary-button" type="button" onClick={() => void acceptProposed()} disabled={busyId !== null || !(data?.items.some((candidate) => candidate.match_state === "proposed"))}>Accept proposed</button></div></div>{loading ? <LoadingState label="Loading candidates…" /> : visibleItems.length === 0 ? <p className="screen-note">No candidates match this filter. Run discovery after connecting an active PSA provider.</p> : <div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">Provider organization</th><th scope="col">Provider</th><th scope="col">Review status</th><th scope="col">Reason</th><th scope="col">Action</th></tr></thead><tbody>{visibleItems.map((candidate) => <tr key={candidate.candidate_id}><td><strong>{candidate.display_name}</strong><br /><code>{candidate.external_id}</code></td><td>{candidate.provenance}</td><td><StatusChip status={stateLabel(candidate.match_state)} /></td><td>{candidate.match_reason || "No exact match"}{candidate.matched_client_id ? ` · ${candidate.matched_client_id}` : ""}</td><td><div className="analytics-filter-actions">{candidate.match_state === "proposed" ? <button type="button" onClick={() => void action(candidate, "accept")} disabled={busyId !== null}>Accept</button> : null}<button className="secondary-button" type="button" onClick={() => void action(candidate, "create-client")} disabled={busyId !== null || candidate.match_state === "verified" || candidate.match_state === "dismissed"}>Create client</button>{candidate.match_state !== "verified" && candidate.match_state !== "dismissed" ? <button className="secondary-button" type="button" onClick={() => void action(candidate, "dismiss")} disabled={busyId !== null}>Dismiss</button> : null}</div></td></tr>)}</tbody></table></div>}</section>
        </div>
      )}
    </RoleGate>
  );
}

export default ClientDiscovery;
