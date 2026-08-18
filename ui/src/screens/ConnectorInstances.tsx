import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import type { ClientConnectorMapping, ClientDirectoryEntry, ConnectorInstance, PollSummary } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

type ConnectorType = "halopsa" | "connectwise";

type ConnectForm = {
  connectorType: ConnectorType;
  displayName: string;
  waitClientId: string;
  baseUrl: string;
  apiVersion: string;
  haloClientId: string;
  clientSecret: string;
  tenant: string;
  company: string;
  publicKey: string;
  privateKey: string;
  connectWiseClientId: string;
};

const initialConnectForm: ConnectForm = {
  connectorType: "halopsa",
  displayName: "",
  waitClientId: "",
  baseUrl: "",
  apiVersion: "2024.1",
  haloClientId: "",
  clientSecret: "",
  tenant: "",
  company: "",
  publicKey: "",
  privateKey: "",
  connectWiseClientId: ""
};

const demoSecretStorageNotice = "Secret storage is unavailable in demo mode — credentials can't be saved here. In a real deployment this stores the credential in the local vault.";

export function ConnectorInstances() {
  const { role, roleResolved } = useDashboard();
  const canView = roleResolved && role === "admin";
  const [instances, setInstances] = useState<ConnectorInstance[]>([]);
  const [waitClients, setWaitClients] = useState<ClientDirectoryEntry[]>([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [mappings, setMappings] = useState<ClientConnectorMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [clientsError, setClientsError] = useState("");
  const [mappingsLoading, setMappingsLoading] = useState(false);
  const [mappingsError, setMappingsError] = useState("");
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncResults, setSyncResults] = useState<Record<string, PollSummary>>({});
  const [syncErrors, setSyncErrors] = useState<Record<string, string>>({});
  const [connectForm, setConnectForm] = useState<ConnectForm>(initialConnectForm);
  const [connectBusy, setConnectBusy] = useState(false);
  const [connectError, setConnectError] = useState("");
  const [connectNotice, setConnectNotice] = useState("");
  const connectBusyRef = useRef(false);
  const mappingRequestId = useRef(0);

  const loadInstances = useCallback(async (): Promise<ConnectorInstance[]> => {
    mappingRequestId.current += 1;
    setLoading(true);
    setError("");
    setSelectedInstanceId(null);
    setMappings([]);
    setMappingsError("");
    try {
      const result = await apiFetch<ConnectorInstance[]>("/connector-instances");
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid Connector Instances data.");
      }
      setInstances(result);
      return result;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Connector Instances.");
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const loadWaitClients = useCallback(async () => {
    setClientsError("");
    try {
      const result = await apiFetch<ClientDirectoryEntry[]>("/clients");
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid WAIT client data.");
      }
      setWaitClients(result.filter((client) => client.client_id !== "__quarantine__"));
    } catch (requestError) {
      setClientsError(requestError instanceof Error ? requestError.message : "Unable to load WAIT clients.");
    }
  }, []);

  useEffect(() => {
    if (canView) {
      void loadInstances();
      void loadWaitClients();
    }
  }, [canView, loadInstances, loadWaitClients]);

  const selectInstance = useCallback(async (instance: ConnectorInstance) => {
    const requestId = ++mappingRequestId.current;
    setSelectedInstanceId(instance.connector_instance_id);
    setMappings([]);
    setMappingsError("");
    setMappingsLoading(true);
    try {
      const result = await apiFetch<ClientConnectorMapping[]>(
        `/client-connector-mappings?connector_instance_id=${encodeURIComponent(instance.connector_instance_id)}`
      );
      if (requestId !== mappingRequestId.current) {
        return;
      }
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid connector mapping data.");
      }
      setMappings(result);
    } catch (requestError) {
      if (requestId === mappingRequestId.current) {
        setMappingsError(requestError instanceof Error ? requestError.message : "Unable to load connector mappings.");
      }
    } finally {
      if (requestId === mappingRequestId.current) {
        setMappingsLoading(false);
      }
    }
  }, []);

  const selectedInstance = instances.find((instance) => instance.connector_instance_id === selectedInstanceId);

  const syncInstance = useCallback(async (instance: ConnectorInstance) => {
    const instanceId = instance.connector_instance_id;
    setSyncingId(instanceId);
    setSyncErrors((current) => {
      const next = { ...current };
      delete next[instanceId];
      return next;
    });
    try {
      const summary = await apiFetch<PollSummary>(`/connectors/instances/${encodeURIComponent(instanceId)}/sync`, {
        method: "POST"
      });
      setSyncResults((current) => ({ ...current, [instanceId]: summary }));
    } catch (requestError) {
      setSyncErrors((current) => ({ ...current, [instanceId]: syncErrorMessage(requestError) }));
    } finally {
      setSyncingId(null);
    }
  }, []);

  const selectedSyncResult = selectedInstance ? syncResults[selectedInstance.connector_instance_id] : undefined;
  const selectedSyncError = selectedInstance ? syncErrors[selectedInstance.connector_instance_id] : undefined;

  const apiVersionValid = connectForm.connectorType !== "connectwise" || /^[0-9]{4}\.[0-9]+$/.test(connectForm.apiVersion.trim());
  const connectFormReady = Boolean(
    connectForm.displayName.trim()
      && connectForm.baseUrl.trim()
      && apiVersionValid
      && (connectForm.connectorType === "halopsa"
        ? connectForm.haloClientId.trim() && connectForm.clientSecret.trim() && connectForm.tenant.trim()
        : connectForm.company.trim() && connectForm.publicKey.trim() && connectForm.privateKey.trim() && connectForm.connectWiseClientId.trim())
  );

  const updateConnectForm = (field: keyof ConnectForm, value: string) => {
    setConnectForm((current) => ({ ...current, [field]: value }));
    setConnectError("");
    setConnectNotice("");
  };

  const connect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (connectBusyRef.current) {
      return;
    }
    if (!connectFormReady) {
      if (!apiVersionValid) {
        setConnectError("ConnectWise API version must use the format YYYY.N, such as 2024.1.");
      }
      return;
    }

    connectBusyRef.current = true;
    setConnectBusy(true);
    setConnectError("");
    setConnectNotice("");
    const connectorType = connectForm.connectorType;
    const displayName = connectForm.displayName.trim();
    const credentialRef = `connector:${connectorType}:${slug(displayName)}:${crypto.randomUUID()}`;
    const credentials: Record<string, string> = connectorType === "halopsa"
      ? {
          client_id: connectForm.haloClientId.trim(),
          client_secret: connectForm.clientSecret.trim(),
          tenant: connectForm.tenant.trim()
        }
      : {
          company: connectForm.company.trim(),
          public_key: connectForm.publicKey.trim(),
          private_key: connectForm.privateKey.trim(),
          client_id: connectForm.connectWiseClientId.trim()
        };
    const config: Record<string, string> = connectorType === "halopsa"
      ? { base_url: connectForm.baseUrl.trim() }
      : { base_url: connectForm.baseUrl.trim(), api_version: connectForm.apiVersion.trim() };

    try {
      await apiFetch<void>("/secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: credentialRef, value: JSON.stringify(credentials) })
      });
    } catch (requestError) {
      setConnectError(requestStatus(requestError) === 403
        ? demoSecretStorageNotice
        : requestError instanceof Error ? requestError.message : "Unable to store the connector credential.");
      connectBusyRef.current = false;
      setConnectBusy(false);
      return;
    }

    let createdInstance: ConnectorInstance;
    try {
      createdInstance = await apiFetch<ConnectorInstance>("/connector-instances", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector_type: connectorType,
          display_name: displayName,
          client_id: connectForm.waitClientId || undefined,
          credential_ref: credentialRef,
          config_json: JSON.stringify(config)
        })
      });
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to create the connector instance.";
      setConnectError(`The credential was stored in the vault but the connector instance could not be created: ${message}. Retry to create it (a new credential will be stored).`);
      connectBusyRef.current = false;
      setConnectBusy(false);
      return;
    }

    try {
      const refreshedInstances = await loadInstances();
      const instanceToSelect = refreshedInstances.find((instance) => instance.connector_instance_id === createdInstance.connector_instance_id);
      if (instanceToSelect) {
        await selectInstance(instanceToSelect);
      }
      setConnectForm((current) => ({ ...initialConnectForm, connectorType: current.connectorType }));
      setConnectNotice(`Connected ${displayName}. Verify it with 'Sync now' / map its companies below.`);
    } catch (requestError) {
      setConnectError(requestError instanceof Error ? requestError.message : "Unable to create the connector instance.");
    } finally {
      connectBusyRef.current = false;
      setConnectBusy(false);
    }
  };

  const fallback = (
    <section className="panel">
      <div className="panel-heading">
        <h2>Connector Instances</h2>
        <span>Integrations</span>
      </div>
      <p className="screen-note">
        {roleResolved
          ? "Administrator role required to view connector instances."
          : "Checking administrator access before loading connector instances."}
      </p>
    </section>
  );

  return (
    <RoleGate role={role} resolved={roleResolved} allowed={["admin"]} fallback={fallback}>
      <div className="screen-stack">
        <section className="panel connector-instances-hero">
          <div>
            <p className="eyebrow">Integrations</p>
            <h2>Connector Instances</h2>
            <p className="screen-note">Review configured connector instances, mappings, and on-demand sync results.</p>
          </div>
          <button className="icon-button" type="button" onClick={() => void loadInstances()} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </section>

        <section className="panel" aria-labelledby="connect-system-heading">
          <div className="panel-heading">
            <div>
              <h2 id="connect-system-heading">Connect a system</h2>
              <span>Administrator setup</span>
            </div>
            <span>Credential vaulting</span>
          </div>
          <p className="screen-note">Connect a supported PSA or ticketing system. More providers are browse-only for now.</p>
          {connectNotice ? <div className="notice" role="status">{connectNotice}</div> : null}
          {connectError ? <div className="notice danger" role="alert">{connectError}</div> : null}
          <form className="draft-form" onSubmit={(event) => void connect(event)}>
            <fieldset>
              <legend>PSA / Ticketing</legend>
              <label htmlFor="connector-provider">Provider</label>
              <select
                id="connector-provider"
                value={connectForm.connectorType}
                onChange={(event) => updateConnectForm("connectorType", event.target.value as ConnectorType)}
              >
                <option value="halopsa">HaloPSA</option>
                <option value="connectwise">ConnectWise</option>
              </select>
            </fieldset>

            <label htmlFor="connector-display-name">Display name
              <input id="connector-display-name" value={connectForm.displayName} onChange={(event) => updateConnectForm("displayName", event.target.value)} required />
            </label>

            <label htmlFor="connector-wait-client">WAIT client (optional)
              <select id="connector-wait-client" value={connectForm.waitClientId} onChange={(event) => updateConnectForm("waitClientId", event.target.value)}>
                <option value="">No WAIT client association</option>
                {waitClients.map((client) => <option key={client.client_id} value={client.client_id}>{client.name} ({client.client_id})</option>)}
              </select>
            </label>
            {clientsError ? <p className="field-error">{clientsError} You can still connect without a WAIT client association.</p> : null}

            <label htmlFor="connector-base-url">Base URL
              <input id="connector-base-url" value={connectForm.baseUrl} onChange={(event) => updateConnectForm("baseUrl", event.target.value)} required />
            </label>

            {connectForm.connectorType === "connectwise" ? (
              <label htmlFor="connector-api-version">API version
                <input
                  id="connector-api-version"
                  value={connectForm.apiVersion}
                  onChange={(event) => updateConnectForm("apiVersion", event.target.value)}
                  aria-invalid={!apiVersionValid}
                  aria-describedby="connector-api-version-hint"
                  required
                />
                <span id="connector-api-version-hint" className="field-help">Use the format YYYY.N, such as 2024.1.</span>
                {!apiVersionValid ? <span className="field-error">Use the format YYYY.N.</span> : null}
              </label>
            ) : null}

            {connectForm.connectorType === "halopsa" ? (
              <>
                <label htmlFor="halopsa-client-id">Client ID
                  <input id="halopsa-client-id" value={connectForm.haloClientId} onChange={(event) => updateConnectForm("haloClientId", event.target.value)} required />
                </label>
                <label htmlFor="halopsa-client-secret">Client secret
                  <input id="halopsa-client-secret" type="password" value={connectForm.clientSecret} onChange={(event) => updateConnectForm("clientSecret", event.target.value)} required />
                </label>
                <label htmlFor="halopsa-tenant">Tenant
                  <input id="halopsa-tenant" value={connectForm.tenant} onChange={(event) => updateConnectForm("tenant", event.target.value)} required />
                </label>
              </>
            ) : (
              <>
                <label htmlFor="connectwise-company">Company
                  <input id="connectwise-company" value={connectForm.company} onChange={(event) => updateConnectForm("company", event.target.value)} required />
                </label>
                <label htmlFor="connectwise-public-key">Public key
                  <input id="connectwise-public-key" value={connectForm.publicKey} onChange={(event) => updateConnectForm("publicKey", event.target.value)} required />
                </label>
                <label htmlFor="connectwise-private-key">Private key
                  <input id="connectwise-private-key" type="password" value={connectForm.privateKey} onChange={(event) => updateConnectForm("privateKey", event.target.value)} required />
                </label>
                <label htmlFor="connectwise-client-id">Client ID
                  <input id="connectwise-client-id" value={connectForm.connectWiseClientId} onChange={(event) => updateConnectForm("connectWiseClientId", event.target.value)} required />
                </label>
              </>
            )}

            <button type="submit" disabled={connectBusy || !connectFormReady}>{connectBusy ? "Connecting…" : "Connect system"}</button>
          </form>
        </section>

        {error ? (
          <div className="notice danger" role="alert">
            <span>{error}</span>
            <button className="secondary-button" type="button" onClick={() => void loadInstances()} disabled={loading}>Try again</button>
          </div>
        ) : null}

        {loading ? (
          <section className="panel" aria-busy="true">
            <p className="screen-note">Loading Connector Instances…</p>
          </section>
        ) : instances.length === 0 ? (
          <section className="panel empty-state">
            <h3>No connector instances are configured.</h3>
            <p>Configured connector instances will appear here for administrator review.</p>
          </section>
        ) : (
          <section className="panel" aria-labelledby="connector-instances-heading">
            <div className="panel-heading">
              <div>
                <h2 id="connector-instances-heading">Configured instances</h2>
                <span>{instances.length} instance{instances.length === 1 ? "" : "s"}</span>
              </div>
              <span>Administrator view</span>
            </div>
            <div className="connector-instances-table-wrap">
              <table className="connector-instances-table">
                <thead>
                  <tr>
                    <th scope="col">Display name</th>
                    <th scope="col">Type</th>
                    <th scope="col">Status</th>
                    <th scope="col">Owning client</th>
                    <th scope="col">Credential</th>
                  </tr>
                </thead>
                <tbody>
                  {instances.map((instance) => {
                    const selected = instance.connector_instance_id === selectedInstanceId;
                    return (
                      <tr key={instance.connector_instance_id}>
                        <td>
                          <button
                            className="connector-instance-select"
                            type="button"
                            aria-pressed={selected}
                            onClick={() => void selectInstance(instance)}
                          >
                            <strong>{instance.display_name}</strong>
                            <code>{instance.connector_instance_id}</code>
                          </button>
                        </td>
                        <td>{instance.connector_type}</td>
                        <td><StatusChip status={instance.status} /></td>
                        <td>{instance.client_id || "Unassigned"}</td>
                        <td><PresenceBadge configured={Boolean(instance.credential_ref)} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <section className="panel connector-instance-mappings" aria-labelledby="connector-mappings-heading">
          <div className="panel-heading">
            <div>
              <h2 id="connector-mappings-heading">External company mappings</h2>
              <span>{selectedInstance ? selectedInstance.display_name : "Select an instance to inspect its mappings"}</span>
            </div>
            {selectedInstance ? (
              <button
                className="secondary-button"
                type="button"
                onClick={() => void syncInstance(selectedInstance)}
                disabled={syncingId !== null}
              >
                {syncingId === selectedInstance.connector_instance_id ? "Syncing…" : "Sync now"}
              </button>
            ) : <span>No instance selected</span>}
          </div>

          {!selectedInstance ? (
            <p className="screen-note">Select a connector instance above to load its external-company to WAIT-client mappings.</p>
          ) : (
            <>
              {selectedSyncError ? (
                <div className="notice danger" role="alert">
                  <span>{selectedSyncError}</span>
                </div>
              ) : null}
              {selectedSyncResult ? (
                <div className="connector-summary" aria-label="Connector sync summary">
                  <strong>Sync result</strong>
                  <span>Status: {selectedSyncResult.status}</span>
                  <span>Written: {selectedSyncResult.written}</span>
                  <span>Quarantined: {selectedSyncResult.quarantined}</span>
                  <span>Pages fetched: {selectedSyncResult.pages_fetched}</span>
                  <span>Reason: {selectedSyncResult.reason || "None reported"}</span>
                </div>
              ) : null}
              {mappingsLoading ? (
                <p className="screen-note" aria-busy="true">Loading mappings…</p>
              ) : mappingsError ? (
                <div className="notice danger" role="alert">
                  <span>{mappingsError}</span>
                  <button className="secondary-button" type="button" onClick={() => void selectInstance(selectedInstance)} disabled={mappingsLoading}>Try again</button>
                </div>
              ) : mappings.length === 0 ? (
                <div className="empty-state">
                  <h3>No mappings are configured.</h3>
                  <p>No external companies are mapped to this connector instance.</p>
                </div>
              ) : (
                <div className="connector-instances-table-wrap">
                  <table className="connector-instances-table">
                    <thead>
                      <tr>
                        <th scope="col">External company</th>
                        <th scope="col">WAIT client</th>
                        <th scope="col">Verification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mappings.map((mapping) => (
                        <tr key={mapping.mapping_id}>
                          <td>
                            <strong>{mapping.external_company_name || mapping.external_company_id}</strong>
                            {mapping.external_company_name ? <code>{mapping.external_company_id}</code> : null}
                          </td>
                          <td>{mapping.client_id}</td>
                          <td><VerificationBadge verified={mapping.verified === 1} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </RoleGate>
  );
}

function requestStatus(error: unknown): number | undefined {
  if (!error || typeof error !== "object" || !("status" in error)) {
    return undefined;
  }
  const status = error.status;
  return typeof status === "number" ? status : undefined;
}

function slug(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "system";
}

function PresenceBadge({ configured }: { configured: boolean }) {
  return <span className={`status-chip ${configured ? "ok" : "neutral"}`}>{configured ? "Configured" : "Not configured"}</span>;
}

function VerificationBadge({ verified }: { verified: boolean }) {
  return <span className={`status-chip ${verified ? "ok" : "warn"}`}>{verified ? "Verified" : "Unverified"}</span>;
}

function syncErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) {
    return "Unable to sync this connector instance.";
  }

  const status = "status" in error && typeof error.status === "number" ? error.status : undefined;
  if (status === 409 && "technicalDetail" in error && typeof error.technicalDetail === "string") {
    const separator = error.technicalDetail.lastIndexOf(": ");
    const detail = separator >= 0 ? error.technicalDetail.slice(separator + 2) : error.technicalDetail;
    if (detail) {
      return detail;
    }
  }
  return error.message;
}
