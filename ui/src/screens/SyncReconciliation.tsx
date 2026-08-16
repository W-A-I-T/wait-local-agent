import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { ConnectorInstance, SyncCursor, UnmappedRecord } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

export function SyncReconciliation() {
  const { role, roleResolved } = useDashboard();
  const canView = roleResolved && role === "admin";
  const [cursors, setCursors] = useState<SyncCursor[]>([]);
  const [records, setRecords] = useState<UnmappedRecord[]>([]);
  const [instances, setInstances] = useState<ConnectorInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [confirmingRecordId, setConfirmingRecordId] = useState<string | null>(null);
  const [resolvingRecordId, setResolvingRecordId] = useState<string | null>(null);

  const loadData = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError("");
    setStatusMessage("");
    setActionError("");
    try {
      const [cursorResult, unmappedResult, instanceResult] = await Promise.all([
        apiFetch<SyncCursor[]>("/ingestion/sync-cursors"),
        apiFetch<UnmappedRecord[]>("/ingestion/unmapped"),
        apiFetch<ConnectorInstance[]>("/connector-instances")
      ]);
      if (!Array.isArray(cursorResult) || !Array.isArray(unmappedResult) || !Array.isArray(instanceResult)) {
        throw new Error("The appliance returned invalid Sync / Reconciliation data.");
      }
      setCursors(cursorResult);
      setRecords(unmappedResult.filter((record) => !record.resolved_at));
      setInstances(instanceResult);
      return true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Sync / Reconciliation.");
      return false;
    } finally {
      setLoading(false);
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
      const refreshed = await loadData();
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
  }, [confirmingRecordId, loadData]);

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
          <button className="icon-button" type="button" onClick={() => void loadData()} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </section>

        {error ? (
          <div className="notice danger" role="alert">
            <span>{error}</span>
            <button className="secondary-button" type="button" onClick={() => void loadData()} disabled={loading}>
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
          </>
        )}
      </div>
    </RoleGate>
  );
}

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
