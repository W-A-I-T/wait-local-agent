import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiFetchBlob } from "../api/client";
import type { DiagnosticsSummary, PackStatus, SupportBundlePreview } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

const FEATURE_FLAGS = [
  ["write_actions_enabled", "Write actions"],
  ["http_probing_enabled", "Live connector checks"],
  ["cloud_fallback_enabled", "Cloud fallback"],
  ["offline_mode", "Offline mode"],
  ["llm_inference_enabled", "Local inference"],
  ["api_auth_required", "Access protection"],
  ["demo_mode", "Demo mode"],
  ["scheduler_enabled", "Scheduler"]
] as const;

export function DiagnosticsSupport() {
  const { isAdmin, role, roleResolved } = useDashboard();
  const [summary, setSummary] = useState<DiagnosticsSummary | null>(null);
  const [packs, setPacks] = useState<PackStatus[]>([]);
  const [preview, setPreview] = useState<SupportBundlePreview | null>(null);
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const canView = roleResolved && isAdmin;

  const refresh = useCallback(async () => {
    setLoading(true);
    setStatusMessage("");
    const results = await Promise.allSettled([
      apiFetch<DiagnosticsSummary>("/diagnostics/summary"),
      apiFetch<PackStatus[]>("/packs/status")
    ]);
    const summaryResult = results[0];
    const packResult = results[1];
    if (summaryResult.status === "fulfilled") {
      setSummary(summaryResult.value);
    }
    if (packResult.status === "fulfilled") {
      setPacks(packResult.value);
    }
    setStatusMessage(
      results.every((result) => result.status === "fulfilled")
        ? "Diagnostics refreshed."
        : "Some diagnostics could not be loaded. Try refreshing again."
    );
    setLoading(false);
  }, []);

  useEffect(() => {
    if (canView) {
      void refresh();
    }
  }, [canView, refresh]);

  async function generatePreview() {
    try {
      setStatusMessage("Preparing the local bundle preview…");
      setPreview(await apiFetch<SupportBundlePreview>("/diagnostics/bundle/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      }));
      setStatusMessage("Preview ready. Review every inclusion and exclusion before downloading.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to prepare the bundle preview.");
    }
  }

  async function downloadBundle() {
    try {
      setStatusMessage("Building the redacted bundle locally…");
      const blob = await apiFetchBlob("/diagnostics/bundle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "wait-support-bundle.zip";
      anchor.click();
      URL.revokeObjectURL(url);
      setStatusMessage("Bundle downloaded for local review.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to download the bundle.");
    }
  }

  async function requestUpload() {
    try {
      await apiFetch("/diagnostics/bundle/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ consent })
      });
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Upload is unavailable.");
    }
  }

  const accessRole = role ?? (isAdmin ? "admin" : "viewer");
  const system = summary?.system && !isDegraded(summary.system) ? summary.system : null;
  const configuration = summary?.configuration && !isDegraded(summary.configuration) ? summary.configuration : null;
  const connectors = summary && Array.isArray(summary.connectors) ? summary.connectors : [];
  const failures = summary && Array.isArray(summary.failed_executions) ? summary.failed_executions : [];
  const hardening = summary?.hardening && !isDegraded(summary.hardening) ? summary.hardening : null;
  const update = summary?.update_status && !isDegraded(summary.update_status) ? summary.update_status : null;
  const uploadDisabledReason = uploadReason(summary);

  return (
    <RoleGate
      role={accessRole}
      resolved={roleResolved}
      allowed={["admin"]}
      fallback={(
        <section className="panel">
          <div className="panel-heading"><h2>Diagnostics &amp; Support</h2><span>System</span></div>
          <p className="screen-note">
            {roleResolved
              ? "Administrator role required to view appliance diagnostics."
              : "Checking administrator access before loading appliance diagnostics."}
          </p>
        </section>
      )}
    >
      <div className="screen-stack">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Diagnostics &amp; Support</h2>
              <p className="screen-note">Safe appliance facts and a locally prepared support archive.</p>
            </div>
            <button className="icon-button" type="button" onClick={() => void refresh()} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          {statusMessage ? <div className="notice" role="status">{statusMessage}</div> : null}
          <div className="table-list settings-list">
            <StatusRow label="Version" value={system?.version} />
            <StatusRow label="Build" value={system?.build_commit ?? "Not recorded"} />
            <StatusRow label="Operating system" value={system?.os_name} />
            <StatusRow label="Install mode" value={system?.install_mode} />
            <StatusRow label="Database integrity" value={databaseIntegrity(summary)} />
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Safe configuration</h2><span>Values are never shown</span></div>
          <div className="flag-grid">
            {FEATURE_FLAGS.map(([key, label]) => {
              const enabled = configuration ? Boolean(configuration[key]) : undefined;
              return (
                <div key={key}>
                  <strong>{label}</strong>
                  <span>{enabled === undefined ? "Not loaded" : enabled ? "Enabled" : "Disabled"}</span>
                  <StatusChip status={enabled === undefined ? "unavailable" : enabled ? "configured" : "not_configured"} />
                </div>
              );
            })}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Connector readiness</h2><span>{connectors.length} connectors</span></div>
          <div className="table-list">
            {connectors.map((connector) => (
              <div className="table-row" key={connector.id}>
                <strong>{connector.id}</strong>
                <StatusChip status={connector.readiness} />
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Recent failed executions</h2><span>{failures.length} retained</span></div>
          {failures.length === 0 ? <p className="screen-note">No recent failed executions were found.</p> : null}
          <div className="event-list">
            {failures.map((failure, index) => (
              <div className="event-row" key={`${failure.run_kind}-${failure.started_at}-${index}`}>
                <strong>{failure.run_kind}</strong>
                <StatusChip status={failure.status} />
                <span>{failure.trigger_source}</span>
                {failure.steps.map((step, stepIndex) => (
                  <p key={`${step.name}-${stepIndex}`}>{step.name}: {step.error || step.status}</p>
                ))}
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Hardening and updates</h2><span>Local status</span></div>
          <div className="table-list settings-list">
            <StatusRow label="Latest hardening run" value={hardening?.status} status={hardening?.status} />
            <StatusRow label="Update check" value={update?.detail} status={update?.status} />
            <StatusRow label="Installed packs" value={String(packs.length)} />
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Diagnostic bundle</h2><span>Local and redacted</span></div>
          <p className="screen-note">Preview the fixed section list before creating an archive. Customer work content is excluded.</p>
          <button type="button" onClick={() => void generatePreview()}>Generate diagnostic bundle</button>
          {preview ? (
            <div className="grid">
              <section>
                <h3>Included</h3>
                <ul>{preview.inclusions.map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
              <section>
                <h3>Excluded</h3>
                <ul>{preview.exclusions.map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
              <div className="row-actions">
                <button type="button" onClick={() => void downloadBundle()}>Download</button>
                <label>
                  <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                  I approve a support transfer
                </label>
                <button
                  type="button"
                  onClick={() => void requestUpload()}
                  disabled={Boolean(uploadDisabledReason) || !consent}
                >
                  Upload
                </button>
              </div>
              {uploadDisabledReason ? <p className="screen-note">{uploadDisabledReason}</p> : null}
            </div>
          ) : null}
        </section>
      </div>
    </RoleGate>
  );
}

function isDegraded(value: object): value is { status: "degraded"; section: string } {
  return "status" in value && value.status === "degraded" && "section" in value;
}

function databaseIntegrity(summary: DiagnosticsSummary | null): string | undefined {
  if (!summary || isDegraded(summary.database)) return undefined;
  return summary.database.integrity_check;
}

function uploadReason(summary: DiagnosticsSummary | null): string {
  if (!summary) return "Upload availability has not been loaded.";
  const configuration = !isDegraded(summary.configuration) ? summary.configuration : null;
  if (configuration?.offline_mode) return "Upload is unavailable while this appliance is offline.";
  if (configuration?.demo_mode) return "Upload is unavailable in demo mode.";
  if (!summary.support_upload.configured) return "No support destination is configured. Download remains available.";
  return "";
}

function StatusRow({ label, value, status }: { label: string; value?: string; status?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value ?? "Not loaded"}{status ? <StatusChip status={status} /> : null}</dd>
    </div>
  );
}
