import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { type ReportExport, type ReportSummary } from "../api/types";

type ReportDetail = Record<string, unknown>;

type RouteReport = ReportSummary & {
  report_url?: string;
};

export function Reports() {
  const [reports, setReports] = useState<RouteReport[]>([]);
  const [reportType, setReportType] = useState("");
  const [clientId, setClientId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [selectedReport, setSelectedReport] = useState<RouteReport | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ReportDetail | null>(null);
  const [exportText, setExportText] = useState("");
  const [statusMessage, setStatusMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const query = new URLSearchParams();
      if (reportType) {
        query.set("report_type", reportType);
      }
      if (clientId) {
        query.set("client_id", clientId);
      }
      if (projectId) {
        query.set("project_id", projectId);
      }
      const path = query.toString() ? `/reports?${query.toString()}` : "/reports";
      const rows = await apiFetch<RouteReport[]>(path);
      setReports(rows);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to load reports.");
    }
  }, [clientId, projectId, reportType]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function openReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedReport) {
      await refresh();
      return;
    }
    try {
      const detail = await apiFetch<ReportExport>(`/reports/${encodeURIComponent(selectedReport.id)}`);
      setSelectedDetail(detail);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to load report detail.");
    }
  }

  async function exportReport(reportId: string, format: "json" | "markdown") {
    try {
      const payload = await apiFetch<ReportExport | string>(
        `/reports/${encodeURIComponent(reportId)}/export?export_format=${format}`
      );
      const text = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
      setExportText(text);
      const blob = new Blob([text], { type: format === "markdown" ? "text/markdown" : "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `wait-report-${reportId}.${format === "markdown" ? "md" : "json"}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Report export failed.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Reports</h2>
          <span>{reports.length} reports</span>
        </div>
        <form className="draft-form" onSubmit={openReport}>
          <div className="grid">
            <label>
              report_type
              <input value={reportType} onChange={(event) => setReportType(event.target.value)} placeholder="collector_bundle" />
            </label>
            <label>
              client_id
              <input value={clientId} onChange={(event) => setClientId(event.target.value)} />
            </label>
            <label>
              project_id
              <input value={projectId} onChange={(event) => setProjectId(event.target.value)} />
            </label>
          </div>
          <div className="row-actions">
            <button type="button" onClick={() => void refresh()} className="icon-button">Refresh</button>
            <button type="submit">Load detail</button>
          </div>
        </form>

        {statusMessage ? <div className="notice">{statusMessage}</div> : null}

        {reports.length === 0 ? <p>No reports available.</p> : null}
        <div className="table-list">
          {reports.map((report) => (
            <article className="table-row" key={report.id}>
              <div>
                <strong>{report.report_type}</strong>
                <span>{report.subject || report.id}</span>
              </div>
              <em>{report.created_at}</em>
              <div>
                <button type="button" className="icon-button" onClick={() => setSelectedReport(report)}>Open</button>
                <button type="button" className="icon-button" onClick={() => void exportReport(report.id, "json")}>
                  Export JSON
                </button>
                <button type="button" className="icon-button" onClick={() => void exportReport(report.id, "markdown")}>
                  Export Markdown
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Report detail</h2>
          <span>{selectedReport ? selectedReport.id : "none selected"}</span>
        </div>
        {selectedDetail ? <pre className="code-panel">{JSON.stringify(selectedDetail, null, 2)}</pre> : <p>Select a report and load detail.</p>}
        {exportText ? <pre className="code-panel">{exportText.slice(0, 1500)}</pre> : null}
      </section>
    </div>
  );
}
