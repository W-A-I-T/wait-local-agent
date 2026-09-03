import { useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import type { AuditEvent } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { ScopeBadge } from "../components/ScopeBadge";

export function Audit() {
  const { selectedClientId } = useDashboard();
  const location = useLocation();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [eventsStatus, setEventsStatus] = useState("");
  const subjectFilter = new URLSearchParams(location.search).get("subject")?.trim() ?? "";

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setEvents(await apiFetch<AuditEvent[]>("/audit"));
    } catch (error) {
      setEventsStatus(error instanceof Error ? error.message : "Unable to load audit." );
    } finally {
      setLoading(false);
    }
  }, [selectedClientId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const visibleEvents = subjectFilter
    ? events.filter((event) => event.subject_id === subjectFilter)
    : events;

  async function exportAuditCsv() {
    try {
      const payload = await apiFetch<string>(exportPath("csv", fromDate, toDate));
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
      const path = exportPath("json", fromDate, toDate);
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
          <div><ScopeBadge /> <span>{visibleEvents.length} events</span></div>
        </div>

        <div className="notice" role="note">
          Audit data stays on this appliance and is never transmitted to WAIT by the runtime. Use Export CSV or
          Export Events JSON below when you choose to save a local copy.
        </div>

        <div className="grid">
          <label>
            From date
            <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          </label>
          <label>
            To date
            <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          </label>
          <button className="icon-button" type="button" onClick={() => void refresh()}>Refresh</button>
          <button type="button" onClick={() => void exportAuditCsv()}>Export CSV</button>
          <button type="button" onClick={() => void exportAuditEventsJson()}>Export Events JSON</button>
        </div>

        {eventsStatus ? <div className="notice">{eventsStatus}</div> : null}
        {exportStatus ? <div className="notice">{exportStatus}</div> : null}

        {subjectFilter ? <p className="screen-note">Showing events for subject {subjectFilter}.</p> : null}
        {loading ? <LoadingState label="Loading audit events…" /> : visibleEvents.length === 0 ? <EmptyState title={subjectFilter ? "No matching audit events" : "No audit events yet"} why="Audit events appear after the appliance records an operator or automation action." /> : <div className="event-list">
          {visibleEvents.map((event) => (
            <div className="event-row" key={event.id}>
              <span>{event.event_type}</span>
              <strong>{event.subject_id}</strong>
              <em>{event.status || "ok"}</em>
              <p>{event.message || event.detail || ""}</p>
              {relatedRunId(event) !== null ? <Link to={`/executions/${relatedRunId(event)}?kind=execution`}>Open related run</Link> : null}
            </div>
          ))}
        </div>}
      </section>
    </div>
  );
}

function relatedRunId(event: AuditEvent): number | null {
  const candidate = event.execution_id ?? event.run_id;
  return typeof candidate === "number" && Number.isInteger(candidate) && candidate > 0 ? candidate : null;
}

function exportPath(format: "json" | "csv", fromDate = "", toDate = ""): string {
  const query = new URLSearchParams({ format });
  if (fromDate) query.set("from", `${fromDate}T00:00:00Z`);
  if (toDate) query.set("to", `${toDate}T23:59:59Z`);
  return `/audit-events/export?${query.toString()}`;
}
