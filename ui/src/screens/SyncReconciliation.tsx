import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api/client";
import type {
  ClientConnectorMapping,
  ClientDirectoryEntry,
  ConnectorInstance,
  MappingVerifyResult,
  QuarantinedTicket,
  SyncCursor,
  UnmappedRecord
} from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

export function SyncReconciliation() {
  const { role, roleResolved } = useDashboard();
  const canView = roleResolved && role === "admin";
  const [cursors, setCursors] = useState<SyncCursor[]>([]);
  const [records, setRecords] = useState<UnmappedRecord[]>([]);
  const [instances, setInstances] = useState<ConnectorInstance[]>([]);
  const [mappings, setMappings] = useState<ClientConnectorMapping[]>([]);
  const [clients, setClients] = useState<ClientDirectoryEntry[]>([]);
  const [quarantinedTickets, setQuarantinedTickets] = useState<QuarantinedTicket[]>([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [quarantinedLoading, setQuarantinedLoading] = useState(false);
  const [quarantinedError, setQuarantinedError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [confirmingRecordId, setConfirmingRecordId] = useState<string | null>(null);
  const [resolvingRecordId, setResolvingRecordId] = useState<string | null>(null);
  const [confirmingMappingId, setConfirmingMappingId] = useState<string | null>(null);
  const [verifyingMappingId, setVerifyingMappingId] = useState<string | null>(null);
  const [confirmingTicketId, setConfirmingTicketId] = useState<string | null>(null);
  const [reclassifyingTicketId, setReclassifyingTicketId] = useState<string | null>(null);
  const [reclassifyClientByTicket, setReclassifyClientByTicket] = useState<Record<string, string>>({});
  const quarantineRequestId = useRef(0);

  const loadData = useCallback(async (quarantineInstanceId = ""): Promise<boolean> => {
    setLoading(true);
    setError("");
    setStatusMessage("");
    setActionError("");
    setQuarantinedError("");
    setQuarantinedLoading(Boolean(quarantineInstanceId));
    const requestId = ++quarantineRequestId.current;
    try {
      const quarantinePromise: Promise<QuarantineLoadResult> = quarantineInstanceId
        ? apiFetch<QuarantinedTicket[]>(
            `/ingestion/quarantined?connector_instance_id=${encodeURIComponent(quarantineInstanceId)}`
          ).then((value) => ({ value })).catch((requestError) => ({ error: requestError }))
        : Promise.resolve({ value: null });
      const [baseResult, quarantineResult] = await Promise.all([
        Promise.all([
        apiFetch<SyncCursor[]>("/ingestion/sync-cursors"),
        apiFetch<UnmappedRecord[]>("/ingestion/unmapped"),
        apiFetch<ConnectorInstance[]>("/connector-instances"),
        apiFetch<ClientConnectorMapping[]>("/client-connector-mappings"),
        apiFetch<ClientDirectoryEntry[]>("/clients")
        ]),
        quarantinePromise
      ]);
      const [cursorResult, unmappedResult, instanceResult, mappingResult, clientResult] = baseResult;
      if (
        !Array.isArray(cursorResult) ||
        !Array.isArray(unmappedResult) ||
        !Array.isArray(instanceResult) ||
        !Array.isArray(mappingResult) ||
        !Array.isArray(clientResult)
      ) {
        throw new Error("The appliance returned invalid Sync / Reconciliation data.");
      }
      setCursors(cursorResult);
      setRecords(unmappedResult.filter((record) => !record.resolved_at));
      setInstances(instanceResult);
      setMappings(mappingResult);
      setClients(clientResult);
      if (requestId === quarantineRequestId.current) {
        if ("error" in quarantineResult) {
          setQuarantinedTickets([]);
          setQuarantinedError(
            quarantineResult.error instanceof Error
              ? quarantineResult.error.message
              : "Unable to load quarantined tickets."
          );
        } else if (quarantineResult.value === null) {
          setQuarantinedTickets([]);
        } else if (!Array.isArray(quarantineResult.value)) {
          setQuarantinedTickets([]);
          setQuarantinedError("The appliance returned invalid quarantined ticket data.");
        } else {
          setQuarantinedTickets(quarantineResult.value);
        }
      }
      return true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Sync / Reconciliation.");
      return false;
    } finally {
      setLoading(false);
      if (requestId === quarantineRequestId.current) {
        setQuarantinedLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (canView) {
      void loadData();
    }
  }, [canView, loadData]);

  const instanceById = useMemo(
    () => new Map(instances.map((instance) => [instance.connector_instance_id, instance])),
    [instances]
  );

  const activeClients = useMemo(
    () => clients.filter((client) => client.client_id !== "__quarantine__" && client.status === "active"),
    [clients]
  );
  const clientById = useMemo(
    () => new Map(clients.map((client) => [client.client_id, client])),
    [clients]
  );

  const requestResolve = useCallback((recordId: string) => {
    setActionError("");
    setConfirmingRecordId(recordId);
  }, []);

  const resolveRecord = useCallback(async () => {
    if (!confirmingRecordId) {
      return;
    }
    const recordId = confirmingRecordId;
    setConfirmingRecordId(null);
    setResolvingRecordId(recordId);
    setActionError("");
    try {
      await apiFetch<UnmappedRecord>(`/ingestion/unmapped/${encodeURIComponent(recordId)}/resolve`, {
        method: "POST"
      });
      const refreshed = await loadData(selectedInstanceId);
      if (refreshed) {
        setStatusMessage("Record marked as reviewed.");
      } else {
        setActionError("Record was marked as reviewed, but the quarantine list could not be refreshed. Try Refresh.");
      }
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : "Unable to mark the record as reviewed.");
    } finally {
      setResolvingRecordId(null);
    }
  }, [confirmingRecordId, loadData, selectedInstanceId]);

  const requestVerifyMapping = useCallback((mappingId: string) => {
    setActionError("");
    setConfirmingMappingId(mappingId);
  }, []);

  const verifyMapping = useCallback(async () => {
    if (!confirmingMappingId) {
      return;
    }
    const mappingId = confirmingMappingId;
    setConfirmingMappingId(null);
    setVerifyingMappingId(mappingId);
    setActionError("");
    try {
      const result = await apiFetch<MappingVerifyResult>(
        `/client-connector-mappings/${encodeURIComponent(mappingId)}/verify`,
        { method: "POST" }
      );
      const refreshed = await loadData(selectedInstanceId);
      if (refreshed) {
        setStatusMessage(`Mapping verified — ${result.retenanted_count} quarantined tickets re-tenanted.`);
      } else {
        setActionError("Mapping was verified, but the reconciliation data could not be refreshed. Try Refresh.");
      }
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : "Unable to verify the mapping.");
    } finally {
      setVerifyingMappingId(null);
    }
  }, [confirmingMappingId, loadData, selectedInstanceId]);

  const requestReclassify = useCallback((ticketId: string) => {
    setActionError("");
    setReclassifyClientByTicket((current) => ({
      ...current,
      [ticketId]: current[ticketId] || activeClients[0]?.client_id || ""
    }));
    setConfirmingTicketId(ticketId);
  }, [activeClients]);

  const reclassifyTicket = useCallback(async () => {
    if (!confirmingTicketId) {
      return;
    }
    const ticketId = confirmingTicketId;
    const clientId = reclassifyClientByTicket[ticketId] || "";
    if (!clientId) {
      setActionError("Select an active client before reclassifying the ticket.");
      return;
    }
    setConfirmingTicketId(null);
    setReclassifyingTicketId(ticketId);
    setActionError("");
    try {
      await apiFetch<{ ticket_id: string; client_id: string }>(
        `/ingestion/quarantined/${encodeURIComponent(ticketId)}/reclassify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: clientId })
        }
      );
      const refreshed = await loadData(selectedInstanceId);
      if (refreshed) {
        setStatusMessage("Quarantined ticket reclassified.");
      } else {
        setActionError("Ticket was reclassified, but the quarantine list could not be refreshed. Try Refresh.");
      }
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : "Unable to reclassify the ticket.");
    } finally {
      setReclassifyingTicketId(null);
    }
  }, [confirmingTicketId, loadData, reclassifyClientByTicket, selectedInstanceId]);

  const fallback = (
    <section className="panel">
      <div className="panel-heading">
        <h2>Sync / Reconciliation</h2>
        <span>Operations</span>
      </div>
      <p className="screen-note">
        {roleResolved
          ? "Administrator role required to view sync and reconciliation details."
          : "Checking administrator access before loading sync and reconciliation details."}
      </p>
    </section>
  );

  return (
    <RoleGate role={role} resolved={roleResolved} allowed={["admin"]} fallback={fallback}>
      <div className="screen-stack">
        <section className="panel sync-reconciliation-hero">
          <div>
            <p className="eyebrow">Operations</p>
            <h2>Sync / Reconciliation Center</h2>
            <p className="screen-note">
              Review connector sync health and resolve records that are waiting for identity mapping.
              This surface does not start or retry syncs.
            </p>
          </div>
          <button className="icon-button" type="button" onClick={() => void loadData(selectedInstanceId)} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </section>

        {error ? (
          <div className="notice danger" role="alert">
            <span>{error}</span>
            <button className="secondary-button" type="button" onClick={() => void loadData(selectedInstanceId)} disabled={loading}>
              Try again
            </button>
          </div>
        ) : null}
        {statusMessage ? <div className="notice" role="status">{statusMessage}</div> : null}
        {actionError ? <div className="notice danger" role="alert">{actionError}</div> : null}

        {loading ? (
          <section className="panel" aria-busy="true">
            <p className="screen-note">Loading Sync / Reconciliation…</p>
          </section>
        ) : (
          <>
            <section className="panel" aria-labelledby="sync-health-heading">
              <div className="panel-heading">
                <div>
                  <h2 id="sync-health-heading">Sync Health</h2>
                  <span>{cursors.length} cursor{cursors.length === 1 ? "" : "s"}</span>
                </div>
                <span>Administrator view</span>
              </div>

              {cursors.length === 0 ? (
                <div className="empty-state">
                  <h3>No sync cursors are recorded.</h3>
                  <p>Connector sync health will appear here when a cursor has been recorded.</p>
                </div>
              ) : (
                <div className="sync-reconciliation-table-wrap">
                  <table className="sync-reconciliation-table">
                    <thead>
                      <tr>
                        <th scope="col">Connector</th>
                        <th scope="col">Cursor type</th>
                        <th scope="col">Status</th>
                        <th scope="col">Last synced</th>
                        <th scope="col">Cursor value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cursors.map((cursor) => (
                        <tr key={`${cursor.connector_instance_id}:${cursor.cursor_type}`}>
                          <td><ConnectorLabel id={cursor.connector_instance_id} instanceById={instanceById} /></td>
                          <td>{cursor.cursor_type}</td>
                          <td><StatusChip status={cursor.status} /></td>
                          <td>{formatTimestamp(cursor.last_synced_at)}</td>
                          <td><code>{cursor.cursor_value || "Not recorded"}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="panel" aria-labelledby="quarantine-heading">
              <div className="panel-heading">
                <div>
                  <h2 id="quarantine-heading">Quarantine / Unmapped</h2>
                  <span>{records.length} record{records.length === 1 ? "" : "s"}</span>
                </div>
                <span>Resolve after review</span>
              </div>

              {records.length === 0 ? (
                <div className="empty-state">
                  <h3>All connectors mapped — nothing quarantined.</h3>
                  <p>New unmapped records will appear here for administrator review.</p>
                </div>
              ) : (
                <div className="sync-reconciliation-table-wrap">
                  <table className="sync-reconciliation-table">
                    <thead>
                      <tr>
                        <th scope="col">Connector</th>
                        <th scope="col">External company</th>
                        <th scope="col">Reason</th>
                        <th scope="col">Record type</th>
                        <th scope="col">Created</th>
                        <th scope="col">Payload digest</th>
                        <th scope="col">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((record) => (
                        <tr key={record.record_id}>
                          <td><ConnectorLabel id={record.connector_instance_id} instanceById={instanceById} /></td>
                          <td>
                            <strong>{record.external_company_id || "Not recorded"}</strong>
                            {record.external_id ? <code>External ID: {record.external_id}</code> : null}
                          </td>
                          <td>{record.reason}</td>
                          <td>{record.record_type}</td>
                          <td>{formatTimestamp(record.created_at)}</td>
                          <td><code>{record.payload_digest || "Not recorded"}</code></td>
                          <td>
                            {confirmingRecordId === record.record_id ? (
                              <div className="reconciliation-confirm" role="alertdialog" aria-label="Confirm record review">
                                <p>Mark this record as reviewed?</p>
                                <div className="row-actions">
                                  <button type="button" onClick={() => void resolveRecord()} disabled={resolvingRecordId !== null}>
                                    Confirm
                                  </button>
                                  <button className="icon-button" type="button" onClick={() => setConfirmingRecordId(null)} disabled={resolvingRecordId !== null}>
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => requestResolve(record.record_id)}
                                disabled={resolvingRecordId !== null}
                                aria-label={`Resolve record ${record.record_id}`}
                              >
                                {resolvingRecordId === record.record_id ? "Resolving…" : "Resolve"}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="panel" aria-labelledby="mappings-pending-heading">
              <div className="panel-heading">
                <div>
                  <h2 id="mappings-pending-heading">Mappings pending verification</h2>
                  <span>{mappings.filter((mapping) => mapping.verified === 0).length} mapping{mappings.filter((mapping) => mapping.verified === 0).length === 1 ? "" : "s"}</span>
                </div>
                <span>Confirm after review</span>
              </div>

              {mappings.filter((mapping) => mapping.verified === 0).length === 0 ? (
                <div className="empty-state">
                  <h3>No mappings awaiting verification.</h3>
                  <p>New external-company mappings will appear here for administrator review.</p>
                </div>
              ) : (
                <div className="sync-reconciliation-table-wrap">
                  <table className="sync-reconciliation-table">
                    <thead>
                      <tr>
                        <th scope="col">Connector</th>
                        <th scope="col">External company</th>
                        <th scope="col">Target client</th>
                        <th scope="col">Created</th>
                        <th scope="col">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mappings.filter((mapping) => mapping.verified === 0).map((mapping) => (
                        <tr key={mapping.mapping_id}>
                          <td><ConnectorLabel id={mapping.connector_instance_id} instanceById={instanceById} /></td>
                          <td>
                            <strong>{mapping.external_company_name || mapping.external_company_id}</strong>
                            {mapping.external_company_name ? <code>{mapping.external_company_id}</code> : null}
                          </td>
                          <td>{clientById.get(mapping.client_id)?.name || mapping.client_id}</td>
                          <td>{formatTimestamp(mapping.created_at)}</td>
                          <td>
                            {confirmingMappingId === mapping.mapping_id ? (
                              <div className="reconciliation-confirm" role="alertdialog" aria-label="Confirm mapping verification">
                                <p>Confirm this connector mapping?</p>
                                <div className="row-actions">
                                  <button type="button" onClick={() => void verifyMapping()} disabled={verifyingMappingId !== null}>
                                    Confirm
                                  </button>
                                  <button className="icon-button" type="button" onClick={() => setConfirmingMappingId(null)} disabled={verifyingMappingId !== null}>
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => requestVerifyMapping(mapping.mapping_id)}
                                disabled={verifyingMappingId !== null}
                                aria-label={`Confirm mapping ${mapping.mapping_id}`}
                              >
                                {verifyingMappingId === mapping.mapping_id ? "Verifying…" : "Confirm mapping"}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="panel" aria-labelledby="quarantined-tickets-heading">
              <div className="panel-heading">
                <div>
                  <h2 id="quarantined-tickets-heading">Quarantined tickets</h2>
                  <span>{selectedInstanceId ? `${quarantinedTickets.length} ticket${quarantinedTickets.length === 1 ? "" : "s"}` : "Connector filter"}</span>
                </div>
                <label>
                  Connector
                  <select
                    aria-label="Quarantined ticket connector"
                    value={selectedInstanceId}
                    onChange={(event) => {
                      const nextInstanceId = event.target.value;
                      setSelectedInstanceId(nextInstanceId);
                      void loadData(nextInstanceId);
                    }}
                    disabled={loading}
                  >
                    <option value="">Select a connector</option>
                    {instances.map((instance) => (
                      <option key={instance.connector_instance_id} value={instance.connector_instance_id}>
                        {instance.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {!selectedInstanceId ? (
                <p className="screen-note">Select a connector to review quarantined tickets.</p>
              ) : quarantinedLoading ? (
                <div className="panel" aria-busy="true">
                  <p className="screen-note">Loading quarantined tickets…</p>
                </div>
              ) : quarantinedError ? (
                <div className="notice danger" role="alert">
                  <span>{quarantinedError}</span>
                  <button className="secondary-button" type="button" onClick={() => void loadData(selectedInstanceId)} disabled={quarantinedLoading}>Try again</button>
                </div>
              ) : quarantinedTickets.length === 0 ? (
                <div className="empty-state">
                  <h3>No quarantined tickets for this connector.</h3>
                  <p>Tickets awaiting a client classification will appear here.</p>
                </div>
              ) : (
                <div className="sync-reconciliation-table-wrap">
                  <table className="sync-reconciliation-table">
                    <thead>
                      <tr>
                        <th scope="col">External ID</th>
                        <th scope="col">Subject</th>
                        <th scope="col">External company</th>
                        <th scope="col">Source system</th>
                        <th scope="col">Created</th>
                        <th scope="col">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {quarantinedTickets.map((ticket) => (
                        <tr key={ticket.id}>
                          <td><code>{ticket.external_id || ticket.id}</code></td>
                          <td>{ticket.subject || "No subject"}</td>
                          <td>{ticket.external_client_id || "Not recorded"}</td>
                          <td>{ticket.source_system || "Not recorded"}</td>
                          <td>{formatTimestamp(ticket.created_at)}</td>
                          <td>
                            {confirmingTicketId === ticket.id ? (
                              <div className="reconciliation-confirm" role="alertdialog" aria-label="Confirm ticket reclassification">
                                <label>
                                  Target client
                                  <select
                                    aria-label="Target client"
                                    value={reclassifyClientByTicket[ticket.id] || ""}
                                    onChange={(event) => setReclassifyClientByTicket((current) => ({ ...current, [ticket.id]: event.target.value }))}
                                  >
                                    <option value="">Select an active client</option>
                                    {activeClients.map((client) => (
                                      <option key={client.client_id} value={client.client_id}>{client.name}</option>
                                    ))}
                                  </select>
                                </label>
                                <div className="row-actions">
                                  <button type="button" onClick={() => void reclassifyTicket()} disabled={reclassifyingTicketId !== null || activeClients.length === 0}>
                                    Confirm
                                  </button>
                                  <button className="icon-button" type="button" onClick={() => setConfirmingTicketId(null)} disabled={reclassifyingTicketId !== null}>
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => requestReclassify(ticket.id)}
                                disabled={reclassifyingTicketId !== null}
                                aria-label={`Reclassify ticket ${ticket.id}`}
                              >
                                {reclassifyingTicketId === ticket.id ? "Reclassifying…" : "Reclassify"}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </RoleGate>
  );
}

type QuarantineLoadResult =
  | { value: QuarantinedTicket[] | null }
  | { error: unknown };

function ConnectorLabel({ id, instanceById }: { id: string; instanceById: Map<string, ConnectorInstance> }) {
  const instance = instanceById.get(id);
  return (
    <span className="sync-reconciliation-connector">
      <strong>{instance?.display_name || id}</strong>
      <span>{instance?.connector_type || "Connector instance"}</span>
    </span>
  );
}

function formatTimestamp(value?: string | null): string {
  return value || "Not recorded";
}
