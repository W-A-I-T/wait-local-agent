import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../api/client";
import type { ClientConnectorMapping, ConnectorInstance } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

export function ConnectorInstances() {
  const { role, roleResolved } = useDashboard();
  const canView = roleResolved && role === "admin";
  const [instances, setInstances] = useState<ConnectorInstance[]>([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null);
  const [mappings, setMappings] = useState<ClientConnectorMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [mappingsLoading, setMappingsLoading] = useState(false);
  const [mappingsError, setMappingsError] = useState("");
  const mappingRequestId = useRef(0);

  const loadInstances = useCallback(async () => {
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
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Connector Instances.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canView) {
      void loadInstances();
    }
  }, [canView, loadInstances]);

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
            <p className="screen-note">Review configured connector instances and their external-company mappings. This screen is read-only.</p>
          </div>
          <button className="icon-button" type="button" onClick={() => void loadInstances()} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
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
            <span>{selectedInstance ? "Read-only" : "No instance selected"}</span>
          </div>

          {!selectedInstance ? (
            <p className="screen-note">Select a connector instance above to load its external-company to WAIT-client mappings.</p>
          ) : mappingsLoading ? (
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
        </section>
      </div>
    </RoleGate>
  );
}

function PresenceBadge({ configured }: { configured: boolean }) {
  return <span className={`status-chip ${configured ? "ok" : "neutral"}`}>{configured ? "Configured" : "Not configured"}</span>;
}

function VerificationBadge({ verified }: { verified: boolean }) {
  return <span className={`status-chip ${verified ? "ok" : "warn"}`}>{verified ? "Verified" : "Unverified"}</span>;
}
