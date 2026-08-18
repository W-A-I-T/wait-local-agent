import { useCallback, useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { apiFetch } from "../api/client";
import type { Client, ClientConnectorMapping, ClientDirectoryEntry, ClientGraph, MappingVerifyResult } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

type ClientForm = { client_id: string; name: string; status: string };
type ClientDetailTab = "details" | "graph";

const detailTabs: Array<{ id: ClientDetailTab; label: string }> = [
  { id: "details", label: "Details" },
  { id: "graph", label: "Operational graph" }
];

function isNotFoundError(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("status" in error)) return false;
  return error.status === 404;
}

const emptyForm: ClientForm = { client_id: "", name: "", status: "active" };

export function Clients() {
  const { role, roleResolved } = useDashboard();
  const canMutate = roleResolved && role === "admin";
  const [clients, setClients] = useState<ClientDirectoryEntry[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);
  const [selectedClient, setSelectedClient] = useState<Client | null>(null);
  const [activeDetailTab, setActiveDetailTab] = useState<ClientDetailTab>("details");
  const [clientGraph, setClientGraph] = useState<ClientGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState("");
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

  const selectClient = useCallback(async (clientId: string) => {
    setSelectedClientId(clientId);
    setSelectedClient(null);
    setActiveDetailTab("details");
    setClientGraph(null);
    setGraphError("");
    setMappings([]);
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
    void apiFetch<ClientGraph>(`/clients/${encodeURIComponent(selectedClientId)}/graph`)
      .then((result) => {
        if (!cancelled) {
          if (!Array.isArray(result.refs) || !Array.isArray(result.links)) throw new Error("The appliance returned invalid operational-graph data.");
          setClientGraph(result);
        }
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setGraphError(isNotFoundError(requestError)
          ? "This client's operational graph is no longer available. Refresh the client list and try again."
          : requestError instanceof Error ? requestError.message : "Unable to load the operational graph.");
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => { cancelled = true; };
  }, [activeDetailTab, selectedClientId]);

  const refsById = new Map((clientGraph?.refs ?? []).map((ref) => [ref.id, ref]));
  const entityName = (refId: number) => {
    const ref = refsById.get(refId);
    return ref ? ref.display_name || ref.external_id : String(refId);
  };

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
    } catch (requestError) {
      setFormError(requestError instanceof Error ? requestError.message : "Unable to save the client.");
    } finally {
      setMutationBusy(false);
    }
  }, [editing, form, loadClients, selectedClient, selectClient]);

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
    } catch (requestError) {
      setMappingError(requestError instanceof Error ? requestError.message : "Unable to verify the mapping.");
    } finally {
      setVerifyingMappingId(null);
    }
  }, [selectedClientId]);

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
          <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}>
            <button className="secondary-button" type="button" onClick={beginCreate}>New client</button>
          </RoleGate>
          <button className="icon-button" type="button" onClick={() => void loadClients()} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>
        </div>
      </section>

      {error ? <div className="notice danger" role="alert"><span>{error}</span><button className="secondary-button" type="button" onClick={() => void loadClients()} disabled={loading}>Try again</button></div> : null}
      {statusMessage ? <div className="notice success" role="status">{statusMessage}</div> : null}

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

      {loading ? <section className="panel" aria-busy="true"><p className="screen-note">Loading Clients…</p></section> : clients.length === 0 ? <section className="panel empty-state"><h3>No clients are visible.</h3><p>The appliance has not returned any clients for this scope.</p></section> : <section className="panel" aria-labelledby="clients-list-heading"><div className="panel-heading"><div><h2 id="clients-list-heading">Client directory</h2><span>{clients.length} client{clients.length === 1 ? "" : "s"}</span></div><span>Select a client for details</span></div><div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">Name</th><th scope="col">Client ID</th><th scope="col">Status</th></tr></thead><tbody>{clients.map((client) => <tr key={client.client_id}><td><button className="table-link" type="button" onClick={() => void selectClient(client.client_id)}>{client.name}</button></td><td><code>{client.client_id}</code></td><td><StatusChip status={client.status} /></td></tr>)}</tbody></table></div></section>}

      {selectedClientId ? <section className="panel" aria-labelledby="client-detail-heading"><div className="panel-heading"><div><h2 id="client-detail-heading">Client detail</h2><span>{selectedClientId}</span></div>{selectedClient ? <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}><button className="secondary-button" type="button" onClick={beginEdit}>Edit client</button></RoleGate> : null}</div>{selectedClient ? <><div className="tab-list" role="tablist" aria-label="Client detail"><div className="row-actions">{detailTabs.map((tab) => <button key={tab.id} id={`client-detail-tab-${tab.id}`} type="button" role="tab" aria-selected={activeDetailTab === tab.id} aria-controls={`client-detail-panel-${tab.id}`} tabIndex={activeDetailTab === tab.id ? 0 : -1} className={activeDetailTab === tab.id ? "selected" : "secondary-button"} onClick={() => selectDetailTab(tab.id)} onKeyDown={handleDetailTabKeyDown}>{tab.label}</button>)}</div></div>{activeDetailTab === "details" ? <div id="client-detail-panel-details" role="tabpanel" aria-labelledby="client-detail-tab-details"><dl className="mcp-detail-grid"><div><dt>Client ID</dt><dd><code>{selectedClient.client_id}</code></dd></div><div><dt>Name</dt><dd>{selectedClient.name}</dd></div><div><dt>Status</dt><dd><StatusChip status={selectedClient.status} /></dd></div><div><dt>Created</dt><dd>{selectedClient.created_at}</dd></div><div><dt>Updated</dt><dd>{selectedClient.updated_at}</dd></div></dl><h3>Connector mappings</h3>{mappingError ? <div className="notice danger" role="alert">{mappingError}</div> : null}{mappings.length === 0 ? <p className="screen-note">No connector mappings are configured for this client.</p> : <div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">External company</th><th scope="col">Connector</th><th scope="col">Verification</th></tr></thead><tbody>{mappings.map((mapping) => <tr key={mapping.mapping_id}><td>{mapping.external_company_name || mapping.external_company_id}</td><td><code>{mapping.connector_instance_id}</code></td><td>{mapping.verified === 1 ? <StatusChip status="verified" /> : <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}><button className="secondary-button" type="button" onClick={() => void verifyMapping(mapping.mapping_id)} disabled={verifyingMappingId !== null}>{verifyingMappingId === mapping.mapping_id ? "Verifying…" : "Verify"}</button></RoleGate>}</td></tr>)}</tbody></table></div>}</div> : <div id="client-detail-panel-graph" role="tabpanel" aria-labelledby="client-detail-tab-graph" aria-busy={graphLoading}><h3>Entities</h3>{graphLoading ? <p className="screen-note">Loading operational graph…</p> : graphError ? <div className="notice danger" role="alert">{graphError}</div> : !clientGraph || clientGraph.refs.length === 0 ? <p className="screen-note">No operational-graph entities are linked to this client yet.</p> : <><div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">Type</th><th scope="col">Name</th><th scope="col">Source</th><th scope="col">External ID</th><th scope="col">Provenance</th></tr></thead><tbody>{clientGraph.refs.map((ref) => <tr key={ref.id}><td><StatusChip status={ref.entity_type} /></td><td>{ref.display_name || ref.external_id}</td><td>{ref.source_system}</td><td><code>{ref.external_id}</code></td><td>{ref.provenance}</td></tr>)}</tbody></table></div><h3>Relationships</h3>{clientGraph.links.length === 0 ? <p className="screen-note">No relationships are linked to these entities.</p> : <div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">From</th><th scope="col">Relationship</th><th scope="col">To</th><th scope="col">Provenance</th></tr></thead><tbody>{clientGraph.links.map((link) => <tr key={link.id}><td>{entityName(link.from_ref_id)}</td><td>{link.link_type}</td><td>{entityName(link.to_ref_id)}</td><td>{link.provenance}</td></tr>)}</tbody></table></div>}</>}</div>}</> : detailLoading ? <p className="screen-note" aria-busy="true">Loading client details…</p> : detailError ? <div className="notice danger" role="alert">{detailError}</div> : null}</section> : null}
    </div>
  );
}
