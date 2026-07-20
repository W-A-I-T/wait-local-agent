import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import type { AuditEvent } from "../api/types";

export function Audit() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [clientId, setClientId] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [eventsStatus, setEventsStatus] = useState("");

  const refresh = useCallback(async () => {
    try {
      const query = new URLSearchParams();
      if (clientId) {
        query.set("client_id", clientId);
      }
      const path = query.toString() ? `/audit?${query.toString()}` : "/audit";
      setEvents(await apiFetch<AuditEvent[]>(path));
    } catch (error) {
      setEventsStatus(error instanceof Error ? error.message : "Unable to load audit." );
    }
  }, [clientId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function exportAuditCsv() {
    try {
      const payload = await apiFetch<{ count?: number; events?: AuditEvent[] } | string>(
        `/audit/export?export_format=csv${clientId ? `&client_id=${encodeURIComponent(clientId)}` : ""}`
      );
      const text = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
      setExportStatus(`Downloaded ${text.length} bytes`);
      const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "wait-audit-events.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportStatus(error instanceof Error ? error.message : "Export failed.");
    }
  }

  async function exportAuditEventsJson() {
    try {
      const path = `/audit-events/export?format=json${clientId ? `&client_id=${encodeURIComponent(clientId)}` : ""}`;
      const payload = await apiFetch<{
        count: number;
        events: AuditEvent[];
      }>(path);
      setExportStatus(`Downloaded ${payload.count} events from audit-events endpoint.`);
      const text = JSON.stringify(payload, null, 2);
      const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "wait-audit-events.json";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportStatus(error instanceof Error ? error.message : "Export failed.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Audit</h2>
          <span>{events.length} events</span>
        </div>

        <div className="grid">
          <label>
            client_id
            <input value={clientId} onChange={(event) => setClientId(event.target.value)} />
          </label>
          <button className="icon-button" type="button" onClick={() => void refresh()}>Refresh</button>
          <button type="button" onClick={() => void exportAuditCsv()}>Export CSV</button>
          <button type="button" onClick={() => void exportAuditEventsJson()}>Export Events JSON</button>
        </div>

        {eventsStatus ? <div className="notice">{eventsStatus}</div> : null}
        {exportStatus ? <div className="notice">{exportStatus}</div> : null}

        {events.length === 0 ? <p>No audit events yet.</p> : null}
        <div className="event-list">
          {events.map((event) => (
            <div className="event-row" key={event.id}>
              <span>{event.event_type}</span>
              <strong>{event.subject_id}</strong>
              <em>{event.status || "ok"}</em>
              <p>{event.message || event.detail || ""}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
