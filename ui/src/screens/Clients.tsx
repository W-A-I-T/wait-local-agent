import { useCallback, useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { ApiRequestError, apiFetch } from "../api/client";
import type { BaselineFinding, Client, ClientBaseline, ClientConnectorMapping, ClientDirectoryEntry, ClientDrift, ClientGraph, CommercialActivation, M365InventorySyncResult, MappingVerifyResult, RmmInventorySyncResult } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

type ClientForm = { client_id: string; name: string; status: string };
type ClientDetailTab = "details" | "graph" | "baseline";

const detailTabs: Array<{ id: ClientDetailTab; label: string }> = [
  { id: "details", label: "Details" },
  { id: "graph", label: "Environment" },
  { id: "baseline", label: "Baseline" }
];

function isNotFoundError(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("status" in error)) return false;
  return error.status === 404;
}

const emptyForm: ClientForm = { client_id: "", name: "", status: "active" };

function groupGraphRefs(refs: ClientGraph["refs"]): ClientGraph["refs"] {
  return [...refs].sort((left, right) =>
    left.entity_type.localeCompare(right.entity_type) || left.display_name.localeCompare(right.display_name)
  );
}

function graphPath(clientId: string, entityType: string, sourceSystem: string, linkType: string, offset: number): string {
  const params = new URLSearchParams();
  if (entityType) params.set("entity_type", entityType);
  if (sourceSystem) params.set("source_system", sourceSystem);
  if (linkType) params.set("link_type", linkType);
  if (offset > 0) params.set("offset", String(offset));
  const query = params.toString();
  return `/clients/${encodeURIComponent(clientId)}/graph${query ? `?${query}` : ""}`;
}

function isStale(lastSeen?: string): boolean {
  if (!lastSeen) return false;
  const timestamp = Date.parse(lastSeen);
  return Number.isFinite(timestamp) && Date.now() - timestamp > 7 * 24 * 60 * 60 * 1000;
}

export function Clients() {
  const {
    role,
    roleResolved,
    isMspAdmin = false,
    commercialEntitlement = null,
    refresh,
    refreshConfiguration = refresh
  } = useDashboard();
  const canMutate = roleResolved && role === "admin";
  const canManageCommercial = roleResolved && isMspAdmin && commercialEntitlement !== null;
  const [clients, setClients] = useState<ClientDirectoryEntry[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);
  const [selectedClient, setSelectedClient] = useState<Client | null>(null);
  const [activeDetailTab, setActiveDetailTab] = useState<ClientDetailTab>("details");
  const [clientGraph, setClientGraph] = useState<ClientGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState("");
  const [rmmSyncLoading, setRmmSyncLoading] = useState(false);
  const [rmmSyncResult, setRmmSyncResult] = useState<RmmInventorySyncResult | null>(null);
  const [rmmSyncError, setRmmSyncError] = useState("");
  const [m365SyncLoading, setM365SyncLoading] = useState(false);
  const [m365SyncResult, setM365SyncResult] = useState<M365InventorySyncResult | null>(null);
  const [m365SyncError, setM365SyncError] = useState("");
  const [graphEntityType, setGraphEntityType] = useState("");
  const [graphSourceSystem, setGraphSourceSystem] = useState("");
  const [graphLinkType, setGraphLinkType] = useState("");
  const [graphOffset, setGraphOffset] = useState(0);
  const [mappings, setMappings] = useState<ClientConnectorMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [mappingError, setMappingError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [form, setForm] = useState<ClientForm>(emptyForm);
  const [editing, setEditing] = useState(false);
  const [mutationBusy, setMutationBusy] = useState(false);
  const [verifyingMappingId, setVerifyingMappingId] = useState<string | null>(null);
  const [formError, setFormError] = useState("");
  const [deploymentMode, setDeploymentMode] = useState<string | null>(null);
  const [baselines, setBaselines] = useState<ClientBaseline[]>([]);
  const [drift, setDrift] = useState<ClientDrift | null>(null);
  const [baselineLoading, setBaselineLoading] = useState(false);
  const [baselineError, setBaselineError] = useState("");
  const [baselineBusy, setBaselineBusy] = useState(false);
  const [commercialActivations, setCommercialActivations] = useState<CommercialActivation[]>([]);
  const [commercialActivationBusy, setCommercialActivationBusy] = useState<string | null>(null);
  const [commercialActivationError, setCommercialActivationError] = useState("");

  const loadClients = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch<ClientDirectoryEntry[]>("/clients");
      if (!Array.isArray(result)) throw new Error("The appliance returned invalid Clients data.");
      setClients(result.filter((client) => client.client_id !== "__quarantine__"));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Clients.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadClients(); }, [loadClients]);
  useEffect(() => {
    void apiFetch<{ mode: string | null }>("/setup/mode")
      .then((result) => setDeploymentMode(result.mode))
      .catch(() => setDeploymentMode(null));
  }, []);

  const loadCommercialActivations = useCallback(async () => {
    if (!canManageCommercial) {
      setCommercialActivations([]);
      setCommercialActivationError("");
      return;
    }
    setCommercialActivationError("");
    try {
      const result = await apiFetch<CommercialActivation[]>("/clients/commercial-activations");
      setCommercialActivations(Array.isArray(result) ? result : []);
    } catch (requestError) {
      setCommercialActivations([]);
      setCommercialActivationError(requestError instanceof Error ? requestError.message : "Unable to load commercial client status.");
    }
  }, [canManageCommercial]);

  useEffect(() => { void loadCommercialActivations(); }, [loadCommercialActivations]);

  const toggleCommercialActivation = useCallback(async (clientId: string) => {
    if (!canManageCommercial) return;
    const active = commercialActivations.some((activation) => activation.client_id === clientId);
    setCommercialActivationBusy(clientId);
    setCommercialActivationError("");
    try {
      if (active) {
        await apiFetch(`/clients/${encodeURIComponent(clientId)}/commercial-activation`, { method: "DELETE" });
        setCommercialActivations((current) => current.filter((activation) => activation.client_id !== clientId));
        setStatusMessage("Commercial client status set to unmanaged.");
      } else {
        const activation = await apiFetch<CommercialActivation>(
          `/clients/${encodeURIComponent(clientId)}/commercial-activation`,
          { method: "POST" }
        );
        setCommercialActivations((current) => current.some((item) => item.client_id === activation.client_id)
          ? current
          : [...current, activation].sort((left, right) => left.client_id.localeCompare(right.client_id)));
        setStatusMessage("Commercial client status set to managed.");
      }
    } catch (requestError) {
      setCommercialActivationError(requestError instanceof Error ? requestError.message : "Unable to update commercial client status.");
    } finally {
      setCommercialActivationBusy(null);
    }
  }, [canManageCommercial, commercialActivations]);

  const selectClient = useCallback(async (clientId: string) => {
    setSelectedClientId(clientId);
    setSelectedClient(null);
    setActiveDetailTab("details");
    setClientGraph(null);
    setGraphError("");
    setRmmSyncResult(null);
    setRmmSyncError("");
    setM365SyncResult(null);
    setM365SyncError("");
    setGraphEntityType("");
    setGraphSourceSystem("");
    setGraphLinkType("");
    setGraphOffset(0);
    setMappings([]);
    setBaselines([]);
    setDrift(null);
    setBaselineError("");
    setDetailLoading(true);
    setDetailError("");
    setMappingError("");
    try {
      const [detail, allMappings] = await Promise.all([
        apiFetch<Client>(`/clients/${encodeURIComponent(clientId)}`),
        apiFetch<ClientConnectorMapping[]>("/client-connector-mappings")
      ]);
      setSelectedClient(detail);
      setMappings(Array.isArray(allMappings) ? allMappings.filter((mapping) => mapping.client_id === clientId) : []);
    } catch (requestError) {
      setDetailError(requestError instanceof Error ? requestError.message : "Unable to load client details.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const selectDetailTab = (tab: ClientDetailTab) => {
    setActiveDetailTab(tab);
  };

  const handleDetailTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = detailTabs.findIndex((tab) => tab.id === activeDetailTab);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (currentIndex + 1) % detailTabs.length;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (currentIndex - 1 + detailTabs.length) % detailTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = detailTabs.length - 1;
    if (nextIndex !== null) {
      event.preventDefault();
      const nextTab = detailTabs[nextIndex];
      setActiveDetailTab(nextTab.id);
      document.getElementById(`client-detail-tab-${nextTab.id}`)?.focus();
    }
  };

  useEffect(() => {
    if (activeDetailTab !== "graph" || !selectedClientId) return;
    let cancelled = false;
    setGraphLoading(true);
    setGraphError("");
    setClientGraph(null);
    void apiFetch<ClientGraph>(graphPath(selectedClientId, graphEntityType, graphSourceSystem, graphLinkType, graphOffset))
      .then((result) => {
        if (!cancelled) {
          if (!Array.isArray(result.refs) || !Array.isArray(result.links)) throw new Error("The appliance returned invalid environment data.");
          setClientGraph({
            ...result,
            total_refs: result.total_refs ?? result.refs.length,
            total_links: result.total_links ?? result.links.length,
            has_more: result.has_more ?? false,
          });
        }
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setGraphError(isNotFoundError(requestError)
          ? "This client's environment is no longer available. Refresh the client list and try again."
          : requestError instanceof Error ? requestError.message : "Unable to load the environment.");
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => { cancelled = true; };
  }, [activeDetailTab, graphEntityType, graphLinkType, graphOffset, graphSourceSystem, selectedClientId]);

  useEffect(() => {
    if (activeDetailTab !== "baseline" || !selectedClientId) return;
    let cancelled = false;
    setBaselineLoading(true);
    setBaselineError("");
    void Promise.all([
      apiFetch<ClientBaseline[]>(`/clients/${encodeURIComponent(selectedClientId)}/baselines`),
      apiFetch<ClientDrift>(`/clients/${encodeURIComponent(selectedClientId)}/drift`).catch((requestError: unknown) => {
        if (isNotFoundError(requestError)) return null;
        throw requestError;
      })
    ])
      .then(([versionList, driftResult]) => {
        if (!cancelled) {
          setBaselines(Array.isArray(versionList) ? versionList : []);
          setDrift(driftResult);
        }
      })
      .catch((requestError: unknown) => {
        if (!cancelled) setBaselineError(requestError instanceof Error ? requestError.message : "Unable to load baseline data.");
      })
      .finally(() => { if (!cancelled) setBaselineLoading(false); });
    return () => { cancelled = true; };
  }, [activeDetailTab, selectedClientId]);

  const createBaseline = useCallback(async () => {
    if (!selectedClientId) return;
    setBaselineBusy(true);
    setBaselineError("");
    try {
      await apiFetch<ClientBaseline>(`/clients/${encodeURIComponent(selectedClientId)}/baselines`, { method: "POST" });
      setStatusMessage("Baseline snapshot created.");
      setActiveDetailTab("baseline");
      const versionList = await apiFetch<ClientBaseline[]>(`/clients/${encodeURIComponent(selectedClientId)}/baselines`);
      setBaselines(versionList);
    } catch (requestError) {
      setBaselineError(requestError instanceof Error ? requestError.message : "Unable to create the baseline.");
    } finally {
      setBaselineBusy(false);
    }
  }, [selectedClientId]);

  const acceptBaseline = useCallback(async (version: number) => {
    if (!selectedClientId) return;
    setBaselineBusy(true);
    setBaselineError("");
    try {
      const accepted = await apiFetch<ClientBaseline>(`/clients/${encodeURIComponent(selectedClientId)}/baselines/${version}/accept`, { method: "POST" });
      setBaselines((current) => current.map((baseline) => ({ ...baseline, accepted: baseline.version === accepted.version })));
      setStatusMessage(`Baseline version ${version} accepted.`);
    } catch (requestError) {
      setBaselineError(requestError instanceof Error ? requestError.message : "Unable to accept the baseline.");
    } finally {
      setBaselineBusy(false);
    }
  }, [selectedClientId]);

  const refsById = new Map((clientGraph?.refs ?? []).map((ref) => [ref.id, ref]));
  const entityName = (refId: number) => {
    const ref = refsById.get(refId);
    return ref ? ref.display_name || ref.external_id : String(refId);
  };
  const entityTypeCounts = clientGraph?.entity_type_counts ?? (clientGraph?.refs ?? []).reduce<Record<string, number>>((counts, ref) => {
    counts[ref.entity_type] = (counts[ref.entity_type] ?? 0) + 1;
    return counts;
  }, {});
  const driftGroups = Object.entries((drift?.findings ?? []).reduce<Record<string, BaselineFinding[]>>((groups, finding) => {
    (groups[finding.classification] ??= []).push(finding);
    return groups;
  }, {}));

  const syncRmmGraph = useCallback(async () => {
    if (!selectedClientId) return;
    setRmmSyncLoading(true);
    setRmmSyncError("");
    setRmmSyncResult(null);
    try {
      const result = await apiFetch<RmmInventorySyncResult>(
        `/clients/${encodeURIComponent(selectedClientId)}/graph/sync-rmm`,
        { method: "POST" }
      );
      setRmmSyncResult(result);
      const graph = await apiFetch<ClientGraph>(graphPath(selectedClientId, graphEntityType, graphSourceSystem, graphLinkType, graphOffset));
      setClientGraph(graph);
    } catch (requestError) {
      setRmmSyncError(requestError instanceof ApiRequestError && requestError.status === 409
        ? "RMM sync is unavailable in the current appliance posture. Approved read access may be disabled or the RMM adapter may be unavailable."
        : requestError instanceof Error ? requestError.message : "Unable to sync the RMM inventory.");
    } finally {
      setRmmSyncLoading(false);
    }
  }, [graphEntityType, graphLinkType, graphOffset, graphSourceSystem, selectedClientId]);

  const syncM365Graph = useCallback(async () => {
    if (!selectedClientId) return;
    setM365SyncLoading(true);
    setM365SyncError("");
    setM365SyncResult(null);
    try {
      const result = await apiFetch<M365InventorySyncResult>(
        `/clients/${encodeURIComponent(selectedClientId)}/graph/sync-m365`,
        { method: "POST" }
      );
      setM365SyncResult(result);
      const graph = await apiFetch<ClientGraph>(graphPath(selectedClientId, graphEntityType, graphSourceSystem, graphLinkType, graphOffset));
      setClientGraph(graph);
    } catch (requestError) {
      setM365SyncError(requestError instanceof ApiRequestError && requestError.status === 409
        ? "Microsoft 365 sync is unavailable. Approved read access may be disabled or the tenant profile may be unavailable."
        : requestError instanceof Error ? requestError.message : "Unable to sync the Microsoft 365 inventory.");
    } finally {
      setM365SyncLoading(false);
    }
  }, [graphEntityType, graphLinkType, graphOffset, graphSourceSystem, selectedClientId]);

  const submitForm = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const clientId = form.client_id.trim();
    const name = form.name.trim();
    if ((!editing && !clientId) || !name) {
      setFormError(editing ? "Client name is required." : "Client ID and name are required.");
      return;
    }
    setMutationBusy(true);
    setFormError("");
    setStatusMessage("");
    try {
      const client = editing && selectedClient
        ? await apiFetch<Client>(`/clients/${encodeURIComponent(selectedClient.client_id)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: form.status })
          })
        : await apiFetch<Client>("/clients", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ client_id: clientId, name })
          });
      setStatusMessage(editing ? "Client updated." : "Client created.");
      setForm(emptyForm);
      setEditing(false);
      await loadClients();
      await selectClient(client.client_id);
      await refreshConfiguration();
    } catch (requestError) {
      setFormError(requestError instanceof Error ? requestError.message : "Unable to save the client.");
    } finally {
      setMutationBusy(false);
    }
  }, [editing, form, loadClients, refreshConfiguration, selectedClient, selectClient]);

  const verifyMapping = useCallback(async (mappingId: string) => {
    setVerifyingMappingId(mappingId);
    setMappingError("");
    try {
      const result = await apiFetch<MappingVerifyResult>(
        `/client-connector-mappings/${encodeURIComponent(mappingId)}/verify`,
        { method: "POST" }
      );
      if (selectedClientId) {
        const refreshed = await apiFetch<ClientConnectorMapping[]>("/client-connector-mappings");
        setMappings(refreshed.filter((mapping) => mapping.client_id === selectedClientId));
      }
      setStatusMessage(`Mapping verified — ${result.retenanted_count} quarantined tickets re-tenanted.`);
      await refreshConfiguration();
    } catch (requestError) {
      setMappingError(requestError instanceof Error ? requestError.message : "Unable to verify the mapping.");
    } finally {
      setVerifyingMappingId(null);
    }
  }, [refreshConfiguration, selectedClientId]);

  const beginCreate = () => {
    setEditing(false);
    setForm(emptyForm);
    setFormError("");
    setStatusMessage("");
  };

  const beginEdit = () => {
    if (!selectedClient) return;
    setEditing(true);
    setForm({ client_id: selectedClient.client_id, name: selectedClient.name, status: selectedClient.status });
    setFormError("");
  };

  return (
    <div className="screen-stack">
      <section className="panel clients-hero">
        <div>
          <p className="eyebrow">Directory</p>
          <h2>Clients</h2>
          <p className="screen-note">Review client records, connector mappings, and lifecycle status.</p>
        </div>
        <div className="analytics-filter-actions">
          <a className="secondary-button" href="/?onboarding=1&step=0">Return to setup</a>
          {deploymentMode !== "smb" ? <Link className="secondary-button" to="/client-discovery">Discover clients</Link> : null}
          <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}>
            <button className="secondary-button" type="button" onClick={beginCreate}>New client</button>
          </RoleGate>
          <button className="icon-button" type="button" onClick={() => void loadClients()} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>
        </div>
      </section>

      {error ? <div className="notice danger" role="alert"><span>{error}</span><button className="secondary-button" type="button" onClick={() => void loadClients()} disabled={loading}>Try again</button></div> : null}
      {statusMessage ? <div className="notice success" role="status">{statusMessage}</div> : null}
      {commercialActivationError ? <div className="notice danger" role="alert">{commercialActivationError}</div> : null}

      <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}>
        <section className="panel" aria-labelledby="client-form-heading">
          <div className="panel-heading"><div><h2 id="client-form-heading">{editing ? "Edit client" : "Create client"}</h2><span>Administrator actions</span></div></div>
          <form onSubmit={(event) => void submitForm(event)}>
            <div className="analytics-filters">
              <label>Client ID<input value={form.client_id} disabled={editing || mutationBusy} onChange={(event) => setForm({ ...form, client_id: event.target.value })} /></label>
              <label>Name<input value={form.name} disabled={editing || mutationBusy} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
              {editing ? <label>Status<select value={form.status} disabled={mutationBusy} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="active">Active</option><option value="archived">Archived</option><option value="quarantine">Quarantine</option></select></label> : null}
            </div>
            {formError ? <p className="notice danger" role="alert">{formError}</p> : null}
            <div className="analytics-filter-actions"><button type="submit" disabled={mutationBusy}>{mutationBusy ? "Saving…" : editing ? "Save changes" : "Create client"}</button>{editing ? <button className="secondary-button" type="button" onClick={beginCreate} disabled={mutationBusy}>Cancel</button> : null}</div>
          </form>
        </section>
      </RoleGate>

      {loading ? <LoadingState label="Loading Clients…" /> : clients.length === 0 ? <EmptyState title="No clients are visible." why={<><span>The appliance has not returned any clients for this scope.</span><span>For demo evaluation only, with writes disabled, seed a client using <code className="copyable-command">wait-local-agent demo seed --client-id demo</code>. This requires <code>WAIT_DEMO_MODE=true</code> and writes disabled.</span></>} /> : <section className="panel" aria-labelledby="clients-list-heading"><div className="panel-heading"><div><h2 id="clients-list-heading">Client directory</h2><span>{clients.length} client{clients.length === 1 ? "" : "s"}</span></div><span>Select a client for details</span></div><div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">Name</th><th scope="col">Client ID</th><th scope="col">Status</th>{canManageCommercial ? <th scope="col">Commercial</th> : null}</tr></thead><tbody>{clients.map((client) => { const managed = commercialActivations.some((activation) => activation.client_id === client.client_id); return <tr key={client.client_id}><td><button className="table-link" type="button" onClick={() => void selectClient(client.client_id)}>{client.name}</button></td><td><code>{client.client_id}</code></td><td><StatusChip status={client.status} /></td>{canManageCommercial ? <td><div className="row-actions"><span className="status-chip neutral">Commercial: {managed ? "managed" : "unmanaged"}</span><button className="secondary-button" type="button" onClick={() => void toggleCommercialActivation(client.client_id)} disabled={commercialActivationBusy !== null}>{commercialActivationBusy === client.client_id ? "Saving…" : managed ? "Set unmanaged" : "Set managed"}</button></div></td> : null}</tr>; })}</tbody></table></div></section>}

      {selectedClientId && activeDetailTab === "graph" ? (
        <section className="panel" aria-labelledby="environment-sync-heading">
          <div className="panel-heading">
            <div>
              <h2 id="environment-sync-heading">Environment inventory</h2>
              <span>Sync device and identity metadata for this client</span>
            </div>
            <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}>
              <div className="row-actions">
              <button className="secondary-button" type="button" onClick={() => void syncRmmGraph()} disabled={rmmSyncLoading || m365SyncLoading}>
                {rmmSyncLoading ? "Syncing…" : "Sync from RMM"}
              </button>
              <button className="secondary-button" type="button" onClick={() => void syncM365Graph()} disabled={rmmSyncLoading || m365SyncLoading}>
                {m365SyncLoading ? "Syncing…" : "Sync from Microsoft 365"}
              </button>
              </div>
            </RoleGate>
          </div>
          {rmmSyncError ? <div className="notice danger" role="alert">{rmmSyncError}</div> : null}
          {rmmSyncResult ? (
            <div className="connection-state" role="status">
              <span>{rmmSyncResult.devices} device{rmmSyncResult.devices === 1 ? "" : "s"} synced</span>
              <span>{rmmSyncResult.alerts} alert{rmmSyncResult.alerts === 1 ? "" : "s"} synced</span>
              <span>{rmmSyncResult.links} relationship{rmmSyncResult.links === 1 ? "" : "s"} linked</span>
              {rmmSyncResult.errors.map((syncError) => <span key={syncError}>Needs attention: {syncError}</span>)}
            </div>
          ) : null}
          {m365SyncError ? <div className="notice danger" role="alert">{m365SyncError}</div> : null}
          {m365SyncResult ? (
            <div className="connection-state" role="status">
              <span>{m365SyncResult.users} user{m365SyncResult.users === 1 ? "" : "s"} synced</span>
              <span>{m365SyncResult.devices} device{m365SyncResult.devices === 1 ? "" : "s"} synced</span>
              <span>{m365SyncResult.links} relationship{m365SyncResult.links === 1 ? "" : "s"} linked</span>
              {m365SyncResult.errors.map((syncError) => <span key={syncError}>Needs attention: {syncError}</span>)}
            </div>
          ) : null}
        </section>
      ) : null}

      {selectedClientId ? <section className="panel" aria-labelledby="client-detail-heading"><div className="panel-heading"><div><h2 id="client-detail-heading">Client detail</h2><span>{selectedClientId}</span></div>{selectedClient ? <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}><button className="secondary-button" type="button" onClick={beginEdit}>Edit client</button></RoleGate> : null}</div>{selectedClient ? <><div className="tab-list" role="tablist" aria-label="Client detail"><div className="row-actions">{detailTabs.map((tab) => <button key={tab.id} id={`client-detail-tab-${tab.id}`} type="button" role="tab" aria-selected={activeDetailTab === tab.id} aria-controls={`client-detail-panel-${tab.id}`} tabIndex={activeDetailTab === tab.id ? 0 : -1} className={activeDetailTab === tab.id ? "selected" : "secondary-button"} onClick={() => selectDetailTab(tab.id)} onKeyDown={handleDetailTabKeyDown}>{tab.label}</button>)}</div></div>{activeDetailTab === "details" ? <div id="client-detail-panel-details" role="tabpanel" aria-labelledby="client-detail-tab-details"><dl className="mcp-detail-grid"><div><dt>Client ID</dt><dd><code>{selectedClient.client_id}</code></dd></div><div><dt>Name</dt><dd>{selectedClient.name}</dd></div><div><dt>Status</dt><dd><StatusChip status={selectedClient.status} /></dd></div><div><dt>Created</dt><dd>{selectedClient.created_at}</dd></div><div><dt>Updated</dt><dd>{selectedClient.updated_at}</dd></div></dl><h3>Connector mappings</h3>{mappingError ? <div className="notice danger" role="alert">{mappingError}</div> : null}{mappings.length === 0 ? <p className="screen-note">No connector mappings are configured for this client.</p> : <div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">External company</th><th scope="col">Connector</th><th scope="col">Verification</th></tr></thead><tbody>{mappings.map((mapping) => <tr key={mapping.mapping_id}><td>{mapping.external_company_name || mapping.external_company_id}</td><td><code>{mapping.connector_instance_id}</code></td><td>{mapping.verified === 1 ? <StatusChip status="verified" /> : <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}><button className="secondary-button" type="button" onClick={() => void verifyMapping(mapping.mapping_id)} disabled={verifyingMappingId !== null}>{verifyingMappingId === mapping.mapping_id ? "Verifying…" : "Verify"}</button></RoleGate>}</td></tr>)}</tbody></table></div>}</div> : activeDetailTab === "graph" ? <div id="client-detail-panel-graph" role="tabpanel" aria-labelledby="client-detail-tab-graph" aria-busy={graphLoading}><div className="analytics-filters"><label>Type<select aria-label="Environment type filter" value={graphEntityType} onChange={(event) => { setGraphEntityType(event.target.value); setGraphOffset(0); }}><option value="">All types</option>{Object.keys(entityTypeCounts).sort().map((type) => <option key={type} value={type}>{type}</option>)}</select></label><label>Source<select aria-label="Environment source filter" value={graphSourceSystem} onChange={(event) => { setGraphSourceSystem(event.target.value); setGraphOffset(0); }}><option value="">All sources</option>{[...new Set((clientGraph?.refs ?? []).map((ref) => ref.source_system))].sort().map((source) => <option key={source} value={source}>{source}</option>)}</select></label><label>Relationship<select aria-label="Environment relationship filter" value={graphLinkType} onChange={(event) => { setGraphLinkType(event.target.value); setGraphOffset(0); }}><option value="">All relationships</option>{[...new Set((clientGraph?.links ?? []).map((link) => link.link_type))].sort().map((type) => <option key={type} value={type}>{type}</option>)}</select></label></div>{clientGraph && !graphLoading ? <div className="connection-state" role="status">{Object.entries(entityTypeCounts).map(([type, count]) => <span key={type}>{type}: {count}</span>)}<span>{clientGraph.total_refs} entities · {clientGraph.total_links} relationships</span></div> : null}<h3>Entities</h3>{graphLoading ? <p className="screen-note">Loading environment…</p> : graphError ? <div className="notice danger" role="alert">{graphError}</div> : !clientGraph || clientGraph.refs.length === 0 ? <p className="screen-note">No environment entities are linked to this client yet.</p> : <><div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">Type</th><th scope="col">Name</th><th scope="col">Source</th><th scope="col">External ID</th><th scope="col">Last seen</th><th scope="col">Provenance</th></tr></thead><tbody>{groupGraphRefs(clientGraph.refs).map((ref) => <tr key={ref.id}><td><StatusChip status={ref.entity_type} /></td><td>{ref.display_name || ref.external_id}</td><td>{ref.source_system}</td><td><code>{ref.external_id}</code></td><td>{isStale(ref.last_seen) ? <span className="screen-note">Stale</span> : ref.last_seen || "—"}</td><td>{ref.provenance}</td></tr>)}</tbody></table></div><h3>Relationships</h3>{clientGraph.links.length === 0 ? <p className="screen-note">No relationships are linked to these entities.</p> : <div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">From</th><th scope="col">Relationship</th><th scope="col">To</th><th scope="col">Provenance</th></tr></thead><tbody>{clientGraph.links.map((link) => <tr key={link.id}><td>{entityName(link.from_ref_id)}</td><td>{link.link_type}</td><td>{entityName(link.to_ref_id)}</td><td>{link.provenance}</td></tr>)}</tbody></table></div>}</>}<div className="analytics-filter-actions"><button className="secondary-button" type="button" onClick={() => setGraphOffset(Math.max(0, graphOffset - 100))} disabled={graphOffset === 0 || graphLoading}>Previous</button><span>Page {Math.floor(graphOffset / 100) + 1}</span><button className="secondary-button" type="button" onClick={() => setGraphOffset(graphOffset + 100)} disabled={!clientGraph?.has_more || graphLoading}>Next</button></div></div> : <div id="client-detail-panel-baseline" role="tabpanel" aria-labelledby="client-detail-tab-baseline" aria-busy={baselineLoading}><div className="panel-heading"><div><h3>Client baseline</h3><span>Versioned observed state and normalized drift</span></div><RoleGate role={role} resolved={roleResolved} allowed={["admin"]}><button className="secondary-button" type="button" onClick={() => void createBaseline()} disabled={baselineBusy}>{baselineBusy ? "Creating…" : "Create snapshot"}</button></RoleGate></div>{baselineError ? <div className="notice danger" role="alert">{baselineError}</div> : null}{baselineLoading ? <p className="screen-note">Loading baseline data…</p> : null}{!baselineLoading && baselines.length === 0 ? <p className="screen-note">No baseline snapshots have been captured.</p> : null}{!baselineLoading && baselines.length > 0 ? <div className="clients-table-wrap"><table className="clients-table"><thead><tr><th>Version</th><th>Generated</th><th>Sources</th><th>State</th><th>Action</th></tr></thead><tbody>{baselines.map((baseline) => <tr key={baseline.baseline_id}><td>{baseline.version}</td><td>{baseline.generated_at}</td><td>{Object.entries(baseline.source_coverage).map(([source, status]) => <StatusChip key={source} status={source + ": " + status} />)}</td><td><StatusChip status={baseline.accepted ? "accepted" : "candidate"} /></td><td>{baseline.accepted ? "Current" : <button className="secondary-button" type="button" onClick={() => void acceptBaseline(baseline.version)} disabled={baselineBusy}>Accept</button>}</td></tr>)}</tbody></table></div> : null}{!baselineLoading && drift && drift.findings.length > 0 ? <><h3>Drift</h3><div className="clients-table-wrap"><table className="clients-table"><thead><tr><th>Finding</th><th>Classification</th><th>Correlation</th></tr></thead><tbody>{driftGroups.flatMap(([classification, group]) => [<tr key={"group-" + classification}><th colSpan={3}>{classification}</th></tr>, ...group.map((finding) => <tr key={finding.path + finding.classification}><td><code>{finding.path}</code></td><td><StatusChip status={finding.classification} /></td><td>{finding.correlation_label || "—"}</td></tr>)])}</tbody></table></div></> : null}</div>}</> : detailLoading ? <p className="screen-note" aria-busy="true">Loading client details…</p> : detailError ? <div className="notice danger" role="alert">{detailError}</div> : null}</section> : null}
    </div>
  );
}
