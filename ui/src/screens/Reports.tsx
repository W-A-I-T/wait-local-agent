import { FormEvent, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useDashboard } from "../app/DashboardContext";
import { ApiRequestError, apiFetch, apiFetchBlob } from "../api/client";
import {
  type EvidenceReport,
  type EvidenceStatus,
  type HardeningCheckResult,
  type HardeningRun,
  type ReportExport,
  type RestoreExercise
} from "../api/types";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

type ReportDetail = Record<string, unknown>;
type EvidenceDisplayStatus = EvidenceStatus | "loading" | "unavailable";
type EvidenceLoadState = "loading" | "loaded" | "unavailable";

const EVIDENCE_COPY: Record<"hardening" | "restore", Record<EvidenceDisplayStatus, string>> = {
  hardening: {
    loading: "Loading hardening evidence",
    not_run: "These checks haven't been run yet",
    no_evidence: "A run was recorded but produced no evidence",
    partial: "Some checks couldn't complete",
    completed: "Checks completed",
    unavailable: "Evidence couldn't be loaded"
  },
  restore: {
    loading: "Loading restore drill evidence",
    not_run: "A restore drill hasn't been run yet",
    no_evidence: "A drill was recorded but produced no evidence",
    partial: "Some parts of the restore drill couldn't complete",
    completed: "Restore drill completed",
    unavailable: "Evidence couldn't be loaded"
  }
};

const CHECK_TITLES: Record<string, string> = {
  "api-auth-token": "Appliance sign-in protection",
  "rbac-roles": "Operator access coverage",
  "vault-permissions": "Secure local storage protection",
  "sqlite-permissions": "Appliance state file protection",
  "backup-recency": "Recent backup availability",
  "update-channel-pinned": "Trusted update source",
  "audit-log": "Activity history availability",
  "data-directory-permissions": "Appliance data folder protection"
};

const CHECK_SCOPES: Record<string, string> = {
  api: "Appliance access",
  secrets: "Secure local storage",
  storage: "Stored appliance data",
  updates: "Software updates"
};

export function Reports() {
  const { role, roleResolved } = useDashboard();
  const [reports, setReports] = useState<EvidenceReport[]>([]);
  const [hardeningRuns, setHardeningRuns] = useState<HardeningRun[]>([]);
  const [restoreExercises, setRestoreExercises] = useState<RestoreExercise[]>([]);
  const [reportType, setReportType] = useState("");
  const [clientId, setClientId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [selectedReport, setSelectedReport] = useState<EvidenceReport | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ReportDetail | null>(null);
  const [exportText, setExportText] = useState("");
  const [restoreSource, setRestoreSource] = useState("");
  const [restoreEncrypted, setRestoreEncrypted] = useState(false);
  const [reportPeriodStart, setReportPeriodStart] = useState("");
  const [reportPeriodEnd, setReportPeriodEnd] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [runningAction, setRunningAction] = useState<"hardening" | "restore" | null>(null);
  const [reportGeneration, setReportGeneration] = useState<
    "qbr" | "automation-opportunity" | "recurring-service-review" | null
  >(null);
  const [loadState, setLoadState] = useState<EvidenceLoadState>("loading");
  const [technicalError, setTechnicalError] = useState("");

  const refresh = useCallback(async () => {
    setLoadState("loading");
    setTechnicalError("");
    try {
      const [reportRows, hardeningRows, restoreRows] = await Promise.all([
        apiFetch<EvidenceReport[]>("/reports"),
        apiFetch<HardeningRun[]>("/hardening/runs"),
        apiFetch<RestoreExercise[]>("/backup/restore-exercises")
      ]);
      setReports(reportRows);
      setHardeningRuns(sortByLatest(hardeningRows, (run) => run.completed_at || run.started_at));
      setRestoreExercises(sortByLatest(restoreRows, (exercise) => exercise.completed_at || exercise.started_at));
      setLoadState("loaded");
    } catch (error) {
      setLoadState("unavailable");
      showError(error, "Unable to load evidence reports.", setStatusMessage, setTechnicalError);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const visibleReports = useMemo(
    () => reports.filter((report) => (
      (!reportType || report.report_type === reportType)
      && (!clientId || report.client_id === clientId)
      && (!projectId || report.project_id === projectId)
    )),
    [clientId, projectId, reportType, reports]
  );
  const latestHardeningReport = latestReport(reports, "appliance_hardening");
  const latestRestoreReport = latestReport(reports, "restore_evidence");
  const latestHardeningRun = hardeningRuns[0];
  const latestRestoreExercise = restoreExercises[0];
  const hardeningStatus = evidenceStatus(latestHardeningReport, latestHardeningRun, loadState);
  const restoreStatus = evidenceStatus(latestRestoreReport, latestRestoreExercise, loadState);

  async function openReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedReport) {
      return;
    }
    try {
      const detail = await apiFetch<ReportExport>(`/reports/${encodeURIComponent(selectedReport.id)}`);
      setSelectedDetail(detail);
    } catch (error) {
      showError(error, "Unable to load report detail.", setStatusMessage, setTechnicalError);
    }
  }

  async function exportReport(report: EvidenceReport, format: "json" | "markdown" | "pdf") {
    try {
      if (format === "pdf") {
        const blob = await apiFetchBlob(`/reports/${encodeURIComponent(report.id)}/export?export_format=pdf`);
        downloadBlob(blob, `wait-report-${report.id}.pdf`);
        setStatusMessage("PDF report downloaded.");
        return;
      }
      const payload = await apiFetch<ReportExport | string>(
        `/reports/${encodeURIComponent(report.id)}/export?export_format=${format}`
      );
      const text = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
      setExportText(text);
      const blob = new Blob([text], { type: format === "markdown" ? "text/markdown" : "application/json" });
      downloadBlob(blob, `wait-report-${report.id}.${format === "markdown" ? "md" : "json"}`);
    } catch (error) {
      showError(error, "Report export failed.", setStatusMessage, setTechnicalError);
    }
  }

  async function runHardening() {
    setRunningAction("hardening");
    try {
      await apiFetch<unknown>("/hardening/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      setStatusMessage("Checks completed. The latest evidence is now shown below.");
      await refresh();
    } catch (error) {
      showError(error, "Checks could not be started.", setStatusMessage, setTechnicalError);
    } finally {
      setRunningAction(null);
    }
  }

  async function runRestoreDrill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!restoreSource.trim()) {
      setStatusMessage("Choose a backup copy to test first.");
      return;
    }
    setRunningAction("restore");
    try {
      await apiFetch<unknown>("/backup/restore-exercises", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backup_id: restoreSource.trim(), encrypted: restoreEncrypted })
      });
      setRestoreSource("");
      setStatusMessage("Restore drill completed. The latest evidence is now shown below.");
      await refresh();
    } catch (error) {
      showError(error, "Restore drill could not be started.", setStatusMessage, setTechnicalError);
    } finally {
      setRunningAction(null);
    }
  }

  async function generateClientReport(
    reportType: "qbr" | "automation-opportunity" | "recurring-service-review"
  ) {
    if (!reportPeriodStart || !reportPeriodEnd) {
      setStatusMessage("Choose a start and end date before generating a client report.");
      return;
    }
    if (reportPeriodEnd < reportPeriodStart) {
      setStatusMessage("The report end date must be on or after the start date.");
      return;
    }
    setReportGeneration(reportType);
    try {
      const report = await apiFetch<EvidenceReport>(`/reports/${reportType}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId.trim() || undefined,
          period_start: reportPeriodStart,
          period_end: reportPeriodEnd
        })
      });
      setSelectedReport(report);
      setSelectedDetail(report);
      setStatusMessage(`${humanize(reportType)} report generated from local evidence.`);
      await refresh();
    } catch (error) {
      showError(error, "The client report could not be generated.", setStatusMessage, setTechnicalError);
    } finally {
      setReportGeneration(null);
    }
  }

  return (
    <div className="screen-stack">
      {statusMessage ? <div className="notice" role="status">{statusMessage}</div> : null}
      {technicalError ? <TechnicalDetails value={technicalError} /> : null}

      <EvidencePanel
        title="Hardening posture"
        description="These checks cover appliance access, stored data, backups, updates, and activity history."
        status={hardeningStatus}
        report={latestHardeningReport}
        onExport={exportReport}
      >
        <RoleGate
          role={role}
          resolved={roleResolved}
          allowed={["admin"]}
          fallback={<p className="screen-note">{roleResolved ? "You have read-only access. An administrator can run these checks." : "Checking your access before actions are available."}</p>}
        >
          <button type="button" disabled={runningAction !== null} onClick={() => void runHardening()}>
            {runningAction === "hardening" ? "Running checks…" : "Run checks now"}
          </button>
        </RoleGate>
        {latestHardeningRun?.results.length ? (
          <div className="evidence-list">
            {latestHardeningRun.results.map((check) => <HardeningCheckCard check={check} key={check.check_id} />)}
          </div>
        ) : hardeningStatus === "not_run" ? (
          <p className="screen-note">Run the checks to record this appliance's current posture and any recommended follow-up.</p>
        ) : null}
      </EvidencePanel>

      <EvidencePanel
        title="Restore drill evidence"
        description="A drill restores a backup into an isolated temporary copy. It never replaces live operational records, and records what was verified."
        status={restoreStatus}
        report={latestRestoreReport}
        onExport={exportReport}
      >
        <RoleGate
          role={role}
          resolved={roleResolved}
          allowed={["admin"]}
          fallback={<p className="screen-note">{roleResolved ? "You have read-only access. An administrator can run a restore drill." : "Checking your access before actions are available."}</p>}
        >
          <form className="restore-drill-form" onSubmit={runRestoreDrill}>
            <label>
              Backup copy to test
              <input
                value={restoreSource}
                onChange={(event) => setRestoreSource(event.target.value)}
                placeholder="Choose the backup copy location"
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={restoreEncrypted}
                onChange={(event) => setRestoreEncrypted(event.target.checked)}
              />
              This backup copy is encrypted
            </label>
            <button type="submit" disabled={runningAction !== null}>
              {runningAction === "restore" ? "Running restore drill…" : "Run a restore drill"}
            </button>
          </form>
        </RoleGate>
        {latestRestoreExercise ? <RestoreExerciseCard exercise={latestRestoreExercise} /> : restoreStatus !== "loading" ? (
          <p className="screen-note">Choose a backup copy above to verify that it can be restored safely.</p>
        ) : null}
      </EvidencePanel>

      <section className="panel">
        <div className="panel-heading">
          <h2>All reports</h2>
          <span>{visibleReports.length} reports</span>
        </div>
        <div className="report-generation panel-subsection">
          <div>
            <h3>Client reports</h3>
            <p className="screen-note">Generate deterministic QBR, automation-opportunity, or recurring service review reports from local ticket and execution evidence. Follow-up candidates are review-only; no workflow or communication is enabled by report generation.</p>
            <p className="screen-note"><a className="inline-link" href="/connectors?view=scalepad-qbr">Review live ScalePad QBR data in Connector Explorer →</a></p>
          </div>
          <div className="grid">
            <label>
              Period start
              <input type="date" value={reportPeriodStart} onChange={(event) => setReportPeriodStart(event.target.value)} />
            </label>
            <label>
              Period end
              <input type="date" value={reportPeriodEnd} onChange={(event) => setReportPeriodEnd(event.target.value)} />
            </label>
          </div>
          <div className="row-actions">
            <button type="button" disabled={reportGeneration !== null} onClick={() => void generateClientReport("qbr")}>{reportGeneration === "qbr" ? "Generating…" : "Generate QBR"}</button>
            <button type="button" className="icon-button" disabled={reportGeneration !== null} onClick={() => void generateClientReport("automation-opportunity")}>{reportGeneration === "automation-opportunity" ? "Generating…" : "Find automation opportunities"}</button>
            <button type="button" className="icon-button" disabled={reportGeneration !== null} onClick={() => void generateClientReport("recurring-service-review")}>{reportGeneration === "recurring-service-review" ? "Generating…" : "Generate service review"}</button>
          </div>
        </div>
        <form className="draft-form" onSubmit={openReport}>
          <div className="grid">
            <label>
              Report type
              <input value={reportType} onChange={(event) => setReportType(event.target.value)} placeholder="Filter reports" />
            </label>
            <label>
              Client scope (admin only; others are bound)
              <input value={clientId} onChange={(event) => setClientId(event.target.value)} />
            </label>
            <label>
              Project
              <input value={projectId} onChange={(event) => setProjectId(event.target.value)} />
            </label>
          </div>
          <div className="row-actions">
            <button type="button" onClick={() => void refresh()} className="icon-button">Refresh</button>
            <button type="submit">Load detail</button>
          </div>
        </form>
        {loadState === "loading" ? <p>Loading reports…</p> : null}
        {loadState === "loaded" && visibleReports.length === 0 ? <p>No reports available.</p> : null}
        <div className="table-list">
          {visibleReports.map((report) => (
            <article className="table-row" key={report.id}>
              <div>
                <strong>{report.title || humanize(report.report_type)}</strong>
                <span>{report.subject || report.id}</span>
              </div>
              <em>{formatWhen(report.created_at)}</em>
              <div>
                <button type="button" className="icon-button" onClick={() => setSelectedReport(report)}>Open</button>
                <button type="button" className="icon-button" onClick={() => void exportReport(report, "json")}>Export JSON</button>
                <button type="button" className="icon-button" onClick={() => void exportReport(report, "markdown")}>Export Markdown</button>
                <button type="button" className="icon-button" onClick={() => void exportReport(report, "pdf")}>Export PDF</button>
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

function EvidencePanel({
  title,
  description,
  status,
  report,
  onExport,
  children
}: {
  title: string;
  description: string;
  status: EvidenceDisplayStatus;
  report?: EvidenceReport;
  onExport: (report: EvidenceReport, format: "json" | "markdown" | "pdf") => Promise<void>;
  children: ReactNode;
}) {
  const kind = title === "Hardening posture" ? "hardening" : "restore";
  return (
    <section className="panel evidence-panel">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          <p className="screen-note">{description}</p>
        </div>
        <StatusChip status={`evidence_${status}`} />
      </div>
      <div className={`evidence-state evidence-${status}`}>
        <strong>{EVIDENCE_COPY[kind][status]}</strong>
        {report ? <span>Latest evidence: {formatWhen(report.created_at)}</span> : null}
      </div>
      <div className="evidence-actions">
        {children}
        <div className="export-actions" aria-label={`${title} exports`}>
          <button type="button" className="icon-button" disabled={!report} onClick={() => report && void onExport(report, "json")}>Export JSON</button>
          <button type="button" className="icon-button" disabled={!report} onClick={() => report && void onExport(report, "markdown")}>Export Markdown</button>
          <button type="button" className="icon-button" disabled={!report} onClick={() => report && void onExport(report, "pdf")}>Export PDF</button>
        </div>
      </div>
    </section>
  );
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function HardeningCheckCard({ check }: { check: HardeningCheckResult }) {
  const failed = check.status === "failed" || check.status === "error";
  return (
    <article className="evidence-result">
      <div>
        <strong>{CHECK_TITLES[check.check_id] ?? check.title}</strong>
        <span>Priority: {humanize(check.severity)}</span>
      </div>
      <StatusChip status={check.status} />
      <span>Coverage: {CHECK_SCOPES[check.scope] ?? humanize(check.scope)}</span>
      {failed ? <p className="remediation-hint">Recommended fix: {check.remediation_hint?.trim() || "Review the technical details, correct the issue, then run this check again."}</p> : null}
      <TechnicalDetails value={{ check_id: check.check_id, evidence: check.evidence, remediation_hint: check.remediation_hint }} />
    </article>
  );
}

function RestoreExerciseCard({ exercise }: { exercise: RestoreExercise }) {
  const validation = parseJson(exercise.validation_json);
  const verified = Array.isArray(validation?.verified_tables) ? validation.verified_tables.length : 0;
  const duration = typeof validation?.duration_seconds === "number" ? validation.duration_seconds : null;
  return (
    <article className="evidence-result restore-result">
      <div>
        <strong>Latest restore drill</strong>
        <span>Ran {formatWhen(exercise.completed_at || exercise.started_at)}</span>
      </div>
      <StatusChip status={exercise.status} />
      <span>{verified ? `Verified ${verified} stored record groups` : "No verified record groups were recorded"}</span>
      {duration !== null ? <span>Duration: {formatDuration(duration)}</span> : null}
      {exercise.status !== "passed" ? <p className="remediation-hint">The drill did not complete. Review the technical details before repeating it.</p> : null}
      <TechnicalDetails value={{ validation, evidence: parseJson(exercise.evidence_json) }} />
    </article>
  );
}

function TechnicalDetails({ value }: { value: unknown }) {
  return (
    <details className="technical-details">
      <summary>Technical details</summary>
      <pre className="code-panel">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function evidenceStatus(
  report: EvidenceReport | undefined,
  record: HardeningRun | RestoreExercise | undefined,
  loadState: EvidenceLoadState
): EvidenceDisplayStatus {
  if (loadState === "unavailable") {
    return "unavailable";
  }
  if (loadState === "loading") {
    return "loading";
  }
  if (report?.evidence_status) {
    return report.evidence_status;
  }
  if (!record) {
    return "not_run";
  }
  return record.status === "completed" || record.status === "passed" ? "completed" : "partial";
}

function showError(
  error: unknown,
  fallback: string,
  setMessage: (message: string) => void,
  setTechnicalError: (detail: string) => void
) {
  if (error instanceof ApiRequestError) {
    setMessage(error.message);
    setTechnicalError(error.technicalDetail);
    return;
  }
  setMessage(fallback);
  setTechnicalError(error instanceof Error ? error.message : fallback);
}

function latestReport(reports: EvidenceReport[], reportType: string): EvidenceReport | undefined {
  return sortByLatest(reports.filter((report) => report.report_type === reportType), (report) => report.created_at)[0];
}

function sortByLatest<T>(items: T[], getDate: (item: T) => string): T[] {
  return [...items].sort((left, right) => Date.parse(getDate(right)) - Date.parse(getDate(left)));
}

function parseJson(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function formatWhen(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatDuration(seconds: number): string {
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} seconds`;
}

function humanize(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : value;
}
