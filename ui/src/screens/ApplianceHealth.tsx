import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import type { ApplianceHealth as ApplianceHealthResponse, HardeningRun, UpdateStatus } from "../api/types";
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

const CONNECTORS: Array<{ key: keyof ApplianceHealthResponse; label: string }> = [
  { key: "halopsa_configured", label: "HaloPSA" },
  { key: "hudu_configured", label: "Hudu" },
  { key: "syncro_configured", label: "Syncro" },
  { key: "servicenow_configured", label: "ServiceNow" },
  { key: "autotask_configured", label: "Autotask" },
  { key: "itglue_configured", label: "IT Glue" },
  { key: "confluence_configured", label: "Confluence" },
  { key: "sharepoint_configured", label: "SharePoint" },
  { key: "m365_configured", label: "Microsoft 365" }
];

export function ApplianceHealth() {
  const { isAdmin, role, roleResolved } = useDashboard();
  const [health, setHealth] = useState<ApplianceHealthResponse | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [hardeningRuns, setHardeningRuns] = useState<HardeningRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
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

  const latestHardeningRun = hardeningRuns[0];
  const accessRole = role ?? (isAdmin ? "admin" : "viewer");

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
            <span>{configuredConnectorCount(health)} of {CONNECTORS.length} configured</span>
          </div>
          <div className="flag-grid">
            {CONNECTORS.map(({ key, label }) => {
              const configured = health ? Boolean(health[key]) : undefined;
              return (
                <div key={key}>
                  <strong>{label}</strong>
                  <span>{configured === undefined ? "Not loaded" : configured ? "Configured" : "Not configured"}</span>
                  <StatusChip status={configured === undefined ? "unavailable" : configured ? "configured" : "not_configured"} />
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
      </div>
    </RoleGate>
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

function configuredConnectorCount(health: ApplianceHealthResponse | null): number {
  if (!health) {
    return 0;
  }
  return CONNECTORS.filter(({ key }) => Boolean(health[key])).length;
}

function sortLatest(runs: HardeningRun[]): HardeningRun[] {
  return [...runs].sort((left, right) => {
    const leftDate = left.completed_at || left.started_at;
    const rightDate = right.completed_at || right.started_at;
    return rightDate.localeCompare(leftDate);
  });
}
