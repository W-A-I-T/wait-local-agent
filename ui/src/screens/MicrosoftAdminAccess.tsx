import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { MICROSOFT_ADMIN_CAPABILITY } from "../hooks/useMicrosoftAdminAccess";

type PrincipalSummary = {
  principal_id: string;
  kind: string;
  display_name: string;
  active: boolean;
  client_roles: Array<[string, string]>;
  global_roles: string[];
};

type CapabilityGrant = {
  principal_id: string;
  capability_key: string;
  client_id: string | null;
  active: boolean;
  granted_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

type Notice = { kind: "success" | "danger"; message: string } | null;

export function MicrosoftAdminAccess() {
  const { clients, refresh: refreshDashboard } = useDashboard();
  const [principals, setPrincipals] = useState<PrincipalSummary[]>([]);
  const [grants, setGrants] = useState<CapabilityGrant[]>([]);
  const [principalId, setPrincipalId] = useState("");
  const [clientId, setClientId] = useState("");
  const [globalScope, setGlobalScope] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  const refresh = useCallback(async (clearNotice = true): Promise<boolean> => {
    setLoading(true);
    if (clearNotice) {
      setNotice(null);
    }
    const results = await Promise.allSettled([
      apiFetch<PrincipalSummary[]>("/packs/microsoft-admin/access/principals"),
      apiFetch<CapabilityGrant[]>(`/packs/microsoft-admin/access/grants?capability_key=${MICROSOFT_ADMIN_CAPABILITY}`)
    ]);
    const failed = results.find((result) => result.status === "rejected") as PromiseRejectedResult | undefined;
    if (failed) {
      setNotice({
        kind: "danger",
        message: failed.reason instanceof Error ? failed.reason.message : "Microsoft Admin access data could not be loaded."
      });
    }
    if (results[0].status === "fulfilled") {
      setPrincipals(Array.isArray(results[0].value) ? results[0].value : []);
    }
    if (results[1].status === "fulfilled") {
      setGrants(Array.isArray(results[1].value) ? results[1].value : []);
    }
    setLoading(false);
    return failed === undefined;
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!principalId && principals[0]) {
      setPrincipalId(principals[0].principal_id);
    }
  }, [principalId, principals]);

  useEffect(() => {
    if (!clientId && clients[0]) {
      setClientId(clients[0].client_id);
    }
  }, [clientId, clients]);

  const selectedPrincipal = useMemo(
    () => principals.find((principal) => principal.principal_id === principalId) ?? null,
    [principalId, principals]
  );

  const eligibleClients = useMemo(() => {
    if (!selectedPrincipal) return [];
    if (selectedPrincipal.global_roles.includes("msp_admin")) return clients;
    const roleClients = new Set(selectedPrincipal.client_roles.map(([id]) => id));
    return clients.filter((client) => roleClients.has(client.client_id));
  }, [clients, selectedPrincipal]);

  useEffect(() => {
    if (!globalScope && eligibleClients.length && !eligibleClients.some((client) => client.client_id === clientId)) {
      setClientId(eligibleClients[0].client_id);
    }
  }, [clientId, eligibleClients, globalScope]);

  async function submitGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!principalId || (!globalScope && !clientId)) return;
    setBusy(true);
    setNotice(null);
    try {
      await apiFetch<CapabilityGrant>("/packs/microsoft-admin/access/grants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          principal_id: principalId,
          capability_key: MICROSOFT_ADMIN_CAPABILITY,
          client_id: globalScope ? null : clientId
        })
      });
      const reloaded = await refresh(false);
      await refreshDashboard();
      if (reloaded) {
        setNotice({ kind: "success", message: "Microsoft Admin access granted." });
      }
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "Grant failed." });
    } finally {
      setBusy(false);
    }
  }

  async function revoke(grant: CapabilityGrant) {
    setBusy(true);
    setNotice(null);
    try {
      await apiFetch<CapabilityGrant>("/packs/microsoft-admin/access/grants/revoke", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          principal_id: grant.principal_id,
          capability_key: grant.capability_key,
          client_id: grant.client_id
        })
      });
      const reloaded = await refresh(false);
      await refreshDashboard();
      if (reloaded) {
        setNotice({ kind: "success", message: "Microsoft Admin access revoked." });
      }
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "Revoke failed." });
    } finally {
      setBusy(false);
    }
  }

  const activeGrants = grants.filter((grant) => grant.active);

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Authorization</p>
            <h2>Microsoft Admin Access</h2>
            <p className="screen-note">
              Assign the Microsoft Admin capability to an existing principal for an exact client. Roles and provider permissions remain separate controls.
            </p>
          </div>
          <button type="button" onClick={() => void refresh()} disabled={loading || busy}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </section>

      {notice ? <div className={`notice ${notice.kind}`} role={notice.kind === "danger" ? "alert" : "status"}>{notice.message}</div> : null}

      <section className="panel" aria-labelledby="capability-grant-heading">
        <h3 id="capability-grant-heading">Grant access</h3>
        {loading ? <LoadingState label="Loading principals and clients…" /> : principals.length === 0 ? <EmptyState title="No principals are available" why="Principals come from configured technician tokens or database principals. A fresh install has none, so configure a technician access identity before granting Microsoft Admin access." /> : <form onSubmit={(event) => void submitGrant(event)}>
          <label htmlFor="capability-principal">Principal</label>
          <select
            id="capability-principal"
            value={principalId}
            disabled={busy || loading || principals.length === 0}
            onChange={(event) => {
              setPrincipalId(event.target.value);
              setGlobalScope(false);
            }}
          >
            {principals.map((principal) => (
              <option key={principal.principal_id} value={principal.principal_id}>
                {principal.display_name} · {principal.principal_id}
              </option>
            ))}
          </select>

          <label>
            <input
              type="checkbox"
              checked={globalScope}
              disabled={busy || !selectedPrincipal?.global_roles.includes("msp_admin")}
              onChange={(event) => setGlobalScope(event.target.checked)}
            />
            Global Microsoft Admin access (MSP admin principals only)
          </label>

          {!globalScope && eligibleClients.length === 0 ? <EmptyState title="No eligible clients are available" why="The selected principal has no client role that matches a configured client. Add the client role or choose another principal." /> : !globalScope ? (
            <>
              <label htmlFor="capability-client">Client</label>
              <select
                id="capability-client"
                value={clientId}
                disabled={busy || eligibleClients.length === 0}
                onChange={(event) => setClientId(event.target.value)}
              >
                {eligibleClients.map((client) => (
                  <option key={client.client_id} value={client.client_id}>{client.name}</option>
                ))}
              </select>
            </>
          ) : null}

          <button
            type="submit"
            disabled={busy || loading || !principalId || (!globalScope && !clientId)}
          >
            {busy ? "Saving…" : "Grant Microsoft Admin"}
          </button>
        </form>}
      </section>

      <section className="panel" aria-labelledby="active-capability-grants-heading">
        <div className="panel-heading">
          <div>
            <h3 id="active-capability-grants-heading">Active grants</h3>
            <span>{activeGrants.length} active Microsoft Admin grant(s)</span>
          </div>
        </div>
        {loading ? <LoadingState label="Loading active grants…" /> : activeGrants.length ? (
          <div className="event-list">
            {activeGrants.map((grant) => (
              <article className="event-row" key={`${grant.principal_id}:${grant.client_id ?? "global"}`}>
                <div>
                  <strong>{grant.principal_id}</strong>
                  <small>{grant.client_id ? `Client: ${grant.client_id}` : "Global MSP scope"}</small>
                  <small>Granted by {grant.granted_by} · updated by {grant.updated_by}</small>
                </div>
                <button type="button" onClick={() => void revoke(grant)} disabled={busy}>Revoke</button>
              </article>
            ))}
          </div>
        ) : <p className="screen-note">No active Microsoft Admin grants.</p>}
      </section>
    </div>
  );
}
