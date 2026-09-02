import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, apiFetch } from "../api/client";
import type { ApplianceHealth as ApplianceHealthResponse, BackupRun, BackupStatusResponse, HardeningRun, UpdateStatus } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

type LoadResult<T> = PromiseSettledResult<T>;

const APPLIANCE_FLAGS: Array<{ key: keyof ApplianceHealthResponse; label: string }> = [
  { key: "write_actions_enabled", label: "Write health" },
  { key: "http_probing_enabled", label: "HTTP probing" },
  { key: "cloud_fallback_enabled", label: "Cloud fallback" },
  { key: "offline_mode", label: "Offline mode" },
  { key: "llm_inference_enabled", label: "LLM inference" },
  { key: "api_auth_required", label: "API authentication" },
  { key: "demo_mode", label: "Demo mode" },
  { key: "scheduler_enabled", label: "Scheduler" }
];

export function ApplianceHealth() {
  const { isAdmin, role, roleResolved } = useDashboard();
  const [health, setHealth] = useState<ApplianceHealthResponse | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [hardeningRuns, setHardeningRuns] = useState<HardeningRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [backupStatus, setBackupStatus] = useState<BackupStatusResponse | null>(null);
  const [backupLoading, setBackupLoading] = useState(false);
  const [backupMessage, setBackupMessage] = useState("");
  const [backupError, setBackupError] = useState("");
  const [confirmingBackup, setConfirmingBackup] = useState(false);
  const backupRunInFlight = useRef(false);
  const canView = roleResolved && isAdmin;

  const refresh = useCallback(async () => {
    setLoading(true);
    setStatusMessage("");
    const results = await Promise.allSettled([
      apiFetch<ApplianceHealthResponse>("/health"),
      apiFetch<UpdateStatus>("/update-status"),
      apiFetch<HardeningRun[]>("/hardening/runs")
    ]);

    const healthResult = results[0] as LoadResult<ApplianceHealthResponse>;
    const updateResult = results[1] as LoadResult<UpdateStatus>;
    const hardeningResult = results[2] as LoadResult<HardeningRun[]>;
    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value);
    }
    if (updateResult.status === "fulfilled") {
      setUpdateStatus(updateResult.value);
    }
    if (hardeningResult.status === "fulfilled") {
      setHardeningRuns(sortLatest(hardeningResult.value));
    }

    const failures = results.filter((result) => result.status === "rejected");
    setStatusMessage(
      failures.length === 0
        ? "Appliance health refreshed."
        : "Some appliance health details could not be loaded. Try refreshing again."
    );
    setLoading(false);
  }, []);

  useEffect(() => {
    if (canView) {
      void refresh();
    }
  }, [canView, refresh]);

  const confirmBackup = async () => {
    if (backupRunInFlight.current || health?.demo_mode !== false) return;
    backupRunInFlight.current = true;
    setBackupLoading(true);
    setConfirmingBackup(false);
    setBackupMessage("");
    setBackupError("");
    try {
      const requestedRun = await apiFetch<BackupRun>("/backups/run", { method: "POST" });
      const status = await apiFetch<BackupStatusResponse>("/backups");
      setBackupStatus(status);
      const recordedRun = status.items.find((run) => run.backup_run_id === requestedRun.backup_run_id) ?? status.items[0];
      if (recordedRun) {
        setBackupMessage(`Backup run ${recordedRun.backup_run_id} recorded with status ${recordedRun.status}.`);
      } else {
        setBackupMessage(`Backup run ${requestedRun.backup_run_id} returned status ${requestedRun.status}, but no run record was found.`);
      }
    } catch (error: unknown) {
      setBackupError(error instanceof ApiRequestError || error instanceof Error
        ? error.message
        : "Unable to run a backup on this appliance.");
    } finally {
      backupRunInFlight.current = false;
      setBackupLoading(false);
    }
  };

  const latestHardeningRun = hardeningRuns[0];
  const accessRole = role ?? (isAdmin ? "admin" : "viewer");
  const configuredConnectors = connectorEntries(health);

  return (
    <RoleGate
      role={accessRole}
      resolved={roleResolved}
      allowed={["admin"]}
      fallback={(
        <section className="panel">
          <div className="panel-heading">
            <h2>Appliance Health</h2>
            <span>System</span>
          </div>
          <p className="screen-note">
            {roleResolved
              ? "Administrator role required to view appliance health."
              : "Checking administrator access before loading appliance health."}
          </p>
        </section>
      )}
    >
      <div className="screen-stack">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Appliance Health</h2>
              <p className="screen-note">Read-only status for this local appliance and its configured services.</p>
            </div>
            <button className="icon-button" type="button" onClick={() => void refresh()} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {statusMessage ? <div className="notice" role="status">{statusMessage}</div> : null}

          <div className="table-list settings-list">
            <StatusRow label="Health status" value={health?.status} status={health?.status} />
            {APPLIANCE_FLAGS.map(({ key, label }) => (
              <StatusRow
                key={key}
                label={label}
                value={health ? formatBoolean(Boolean(health[key])) : undefined}
                status={health ? (health[key] ? "enabled" : "disabled") : undefined}
              />
            ))}
            <StatusRow label="Secrets backend" value={health?.secrets_backend} />
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>Configured connectors</h2>
            <span>{configuredConnectors.filter(([, configured]) => configured).length} of {configuredConnectors.length} configured</span>
          </div>
          <div className="flag-grid">
            {configuredConnectors.length === 0 ? <p className="screen-note">Connector configuration has not been returned yet.</p> : configuredConnectors.map(([key, configured]) => {
              return (
                <div key={key}>
                  <strong>{connectorLabel(key)}</strong>
                  <span>{configured ? "Configured" : "Not configured"}</span>
                  <StatusChip status={configured ? "configured" : "not_configured"} />
                </div>
              );
            })}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>Update status</h2>
            <span>Signed update check</span>
          </div>
          {updateStatus ? (
            <div className="connection-state">
              <StatusChip status={updateStatus.status} />
              <p>{updateStatus.detail}</p>
              {updateStatus.version ? <span>Installed version: {updateStatus.version}</span> : null}
              {updateStatus.target_version ? <span>Target version: {updateStatus.target_version}</span> : null}
            </div>
          ) : <p className="screen-note">Update status is not available yet.</p>}
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>Latest hardening run</h2>
            <span>Read-only evidence</span>
          </div>
          {latestHardeningRun ? (
            <div className="connection-state">
              <StatusChip status={latestHardeningRun.status} />
              <span>Run {latestHardeningRun.id ?? "unknown"}</span>
              <span>{latestHardeningRun.result_count} of {latestHardeningRun.expected_check_count} checks recorded</span>
              <span>Completed: {latestHardeningRun.completed_at || "in progress"}</span>
            </div>
          ) : <p className="screen-note">No hardening runs have been recorded yet.</p>}
        </section>

        <section className="panel" aria-labelledby="backup-run-heading">
          <div className="panel-heading">
            <div>
              <h2 id="backup-run-heading">On-demand backup</h2>
              <p className="screen-note">Create an encrypted appliance backup and verify its persisted run record.</p>
            </div>
            <span>{backupStatus?.total ?? "admin only"}</span>
          </div>

          {health?.demo_mode === true ? (
            <p className="screen-note">Backup runs are unavailable in demo mode.</p>
          ) : health === null ? (
            <p className="screen-note">Backup controls will be available after appliance health loads.</p>
          ) : null}
          {backupError ? <div className="notice danger" role="alert">{backupError}</div> : null}
          {backupMessage ? <div className="notice" role="status">{backupMessage}</div> : null}

          <button
            type="button"
            disabled={backupLoading || health?.demo_mode !== false}
            title={health?.demo_mode === true ? "Backup runs are unavailable in demo mode" : undefined}
            onClick={() => setConfirmingBackup(true)}
          >
            {backupLoading ? "Running backup…" : "Run backup now"}
          </button>

          {confirmingBackup ? (
            <div className="notice confirm-panel" role="alertdialog" aria-label="Confirm backup run">
              <p>Run an encrypted backup now? This may take a moment and will create a new appliance backup record.</p>
              <div className="row-actions">
                <button type="button" onClick={() => void confirmBackup()} disabled={backupLoading}>Confirm backup run</button>
                <button type="button" className="icon-button" onClick={() => setConfirmingBackup(false)} disabled={backupLoading}>Cancel</button>
              </div>
            </div>
          ) : null}

          {backupStatus?.items[0] ? <BackupRunSummary run={backupStatus.items[0]} /> : null}
        </section>
      </div>
    </RoleGate>
  );
}

function BackupRunSummary({ run }: { run: BackupRun }) {
  return (
    <div className="connection-state" aria-label="Latest backup run">
      <StatusChip status={run.status} />
      <span>Run {run.backup_run_id}</span>
      <span>Size: {formatBytes(run.size_bytes)}</span>
      <span>Finished: {run.finished_at || run.started_at || "Not recorded"}</span>
      {run.failure_summary ? <span>{run.failure_summary}</span> : null}
    </div>
  );
}

function StatusRow({ label, value, status }: { label: string; value?: string; status?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value ?? "Not loaded"}
        {status ? <StatusChip status={status} /> : null}
      </dd>
    </div>
  );
}

function formatBoolean(value: boolean): string {
  return value ? "Enabled" : "Disabled";
}

function connectorEntries(health: ApplianceHealthResponse | null): Array<[string, boolean]> {
  if (!health) return [];
  return Object.entries(health)
    .filter(([key, value]) => key.endsWith("_configured") && typeof value === "boolean")
    .sort(([left], [right]) => left.localeCompare(right)) as Array<[string, boolean]>;
}

function connectorLabel(key: string): string {
  const knownLabels: Record<string, string> = {
    halopsa_configured: "HaloPSA",
    hudu_configured: "Hudu",
    syncro_configured: "Syncro",
    servicenow_configured: "ServiceNow",
    autotask_configured: "Autotask",
    itglue_configured: "IT Glue",
    confluence_configured: "Confluence",
    sharepoint_configured: "SharePoint",
    m365_configured: "Microsoft 365"
  };
  if (knownLabels[key]) return knownLabels[key];
  return key
    .replace(/_configured$/, "")
    .split("_")
    .map((part) => part.toUpperCase() === "M365" ? "Microsoft 365" : part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function sortLatest(runs: HardeningRun[]): HardeningRun[] {
  return [...runs].sort((left, right) => {
    const leftDate = left.completed_at || left.started_at;
    const rightDate = right.completed_at || right.started_at;
    return rightDate.localeCompare(leftDate);
  });
}

function formatBytes(value: number | null): string {
  if (value === null) return "Not recorded";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
