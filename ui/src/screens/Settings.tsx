import { FormEvent, useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError, apiFetch } from "../api/client";
import { projectLaunchPassportStatus } from "../api/founder";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";
import { type LaunchPassportStatus, type PackInfo, type ProviderHealth, type ProviderSettings, type SecretRecord, type SecuritySettings, type UpdateStatus } from "../api/types";
import { connectorSetupEnvVarNames } from "../lib/connectorSetup";

export function Settings() {
  const { authState, isAdmin, loading, recheckWriteHealth: recheckDashboardWriteHealth, role } = useDashboard();
  const accessRole = role ?? (isAdmin ? "admin" : "viewer");
  const canViewLaunchPassport = !loading && accessRole === "admin";
  const [providers, setProviders] = useState<ProviderSettings | null>(null);
  const [providerHealth, setProviderHealth] = useState<ProviderHealth | null>(null);
  const [security, setSecurity] = useState<SecuritySettings | null>(null);
  const [packs, setPacks] = useState<PackInfo[]>([]);
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [secretLoadState, setSecretLoadState] = useState<"available" | "demo_unavailable" | "unavailable">("available");
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [launchPassport, setLaunchPassport] = useState<LaunchPassportStatus | null>(null);
  const [launchPassportState, setLaunchPassportState] = useState<"loading" | "not_configured" | "available" | "unavailable">("loading");
  const [writeHealthChecking, setWriteHealthChecking] = useState(false);

  const [packPath, setPackPath] = useState("");
  const [secretName, setSecretName] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [backupPath, setBackupPath] = useState("");
  const [backupEncrypt, setBackupEncrypt] = useState(false);
  const [restoreSource, setRestoreSource] = useState("");
  const [restoreEncrypt, setRestoreEncrypt] = useState(false);
  const [restoreAcknowledged, setRestoreAcknowledged] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [providerRows, securityRows, packRows, secretResult, updateRows, launchPassportResult] = await Promise.all([
        apiFetch<ProviderSettings>("/settings/providers"),
        apiFetch<SecuritySettings>("/settings/security"),
        apiFetch<PackInfo[]>("/packs"),
        apiFetch<SecretRecord[]>("/secrets").then(
          (value) => ({ kind: "available" as const, value }),
          (error: unknown) => ({ kind: "unavailable" as const, error })
        ),
        apiFetch<UpdateStatus>("/update-status"),
        canViewLaunchPassport
          ? apiFetch<LaunchPassportStatus>("/founder/lp-status").then(
            (value) => ({ kind: "available" as const, value }),
            (error: unknown) => ({ kind: "unavailable" as const, error })
          )
          : Promise.resolve({ kind: "not_requested" as const })
      ]);
      setProviders(providerRows);
      setSecurity(securityRows);
      setPacks(packRows);
      if (secretResult.kind === "available") {
        setSecrets(secretResult.value);
        setSecretLoadState("available");
      } else {
        setSecrets([]);
        setSecretLoadState(isDemoModeSecretsUnavailable(secretResult.error, securityRows) ? "demo_unavailable" : "unavailable");
      }
      setStatus(updateRows);
      if (launchPassportResult.kind === "available") {
        setLaunchPassport(projectLaunchPassportStatus(launchPassportResult.value));
        setLaunchPassportState("available");
      } else if (launchPassportResult.kind === "unavailable" && isLaunchPassportNotConfigured(launchPassportResult.error)) {
        setLaunchPassport(null);
        setLaunchPassportState("not_configured");
      } else {
        setLaunchPassport(null);
        setLaunchPassportState("unavailable");
      }
      setStatusMessage("Settings loaded.");
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 403) {
        setStatusMessage(
          authState === "invalid-token"
            ? "Access credential rejected. Return to sign in and try again."
            : `Administrator role required for admin settings. Current role: ${accessRole}.`
        );
        return;
      }
      setStatusMessage(error instanceof Error ? error.message : "Unable to load settings.");
    }
  }, [accessRole, authState, canViewLaunchPassport]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function checkProviderHealth() {
    try {
      setStatusMessage("Checking configured model providers…");
      setProviderHealth(await apiFetch<ProviderHealth>("/settings/providers/health"));
      setStatusMessage("Provider health check complete.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to check provider health.");
    }
  }

  async function installPack(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!packPath) {
      setStatusMessage("Set a pack tarball path first.");
      return;
    }
    try {
      const body = await apiFetch<Record<string, string | number | boolean | null>>("/packs/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tarball_path: packPath })
      });
      setStatusMessage(`Pack installed: ${(body as { pack_name?: string }).pack_name || "done"}.`);
      await refresh();
      setPackPath("");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Install failed.");
    }
  }

  async function createBackup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!backupPath) {
      setStatusMessage("Set a backup destination first.");
      return;
    }
    try {
      await apiFetch<Record<string, string>>("/backups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ destination: backupPath, encrypt: backupEncrypt })
      });
      setStatusMessage("Backup requested.");
      setBackupPath("");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Backup failed.");
    }
  }

  async function restoreBackup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!restoreSource) {
      setStatusMessage("Set restore source path first.");
      return;
    }
    try {
      await apiFetch<Record<string, string>>("/backups/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: restoreSource, encrypted: restoreEncrypt })
      });
      setStatusMessage("Restore requested.");
      setRestoreSource("");
      setRestoreAcknowledged(false);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Restore failed.");
    }
  }

  async function saveSecret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!secretName || !secretValue) {
      setStatusMessage("Secret name and value required.");
      return;
    }
    try {
      await apiFetch<{ name: string }>("/secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: secretName, value: secretValue })
      });
      setStatusMessage(`Secret ${secretName} stored.`);
      setSecretName("");
      setSecretValue("");
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Store secret failed.");
    }
  }

  async function checkForUpdates() {
    try {
      const value = await apiFetch<UpdateStatus>("/update-check", { method: "POST" });
      setStatus(value);
      setStatusMessage("Update check complete.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Update check failed.");
    }
  }

  async function recheckWriteHealth() {
    setWriteHealthChecking(true);
    try {
      await recheckDashboardWriteHealth();
      setStatusMessage("Write health re-check complete.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to re-check write health.");
    } finally {
      setWriteHealthChecking(false);
    }
  }

  return (
    <section className="screen-stack">
      <SettingsGroup id="settings-appliance-heading" title="Appliance" description="Mode, updates, backups, and health checks for this appliance.">
        <section className="panel settings-panel">
          <div className="panel-heading">
            <h2>Admin Settings</h2>
            <span>{isAdmin ? "admin mode" : "viewer mode"}</span>
          </div>
          <div className="row-actions">
            <Link className="icon-button" to="/?onboarding=1">Launch onboarding</Link>
            <button className="icon-button" type="button" onClick={() => void recheckWriteHealth()} disabled={writeHealthChecking}>
              {writeHealthChecking ? "Re-checking…" : "Re-check"}
            </button>
            {isAdmin ? <button className="icon-button" type="button" onClick={() => void checkForUpdates()}>Check for updates</button> : null}
          </div>

          {statusMessage ? <div className="notice">{statusMessage}</div> : null}
          {!isAdmin ? (
            <div className="notice danger">
              {authState === "invalid-token"
                ? "Access credential rejected. Return to sign in and try again."
                : `Administrator role required for write controls. Current role: ${accessRole}.`}
            </div>
          ) : null}

          <div className="table-list settings-list">
            <div><dt>Write health</dt><dd>{security?.api_token_configured ? "Access token saved" : "No access token configured"}</dd></div>
            <div><dt>Update check</dt><dd>{status?.status || "idle"}</dd></div>
            <div><dt>AI model</dt><dd>{providers?.local_model_provider || "n/a"}</dd></div>
            <div><dt>Provider scope</dt><dd>{providers?.provider_scope || "unknown"}</dd></div>
            <div><dt>Request context</dt><dd>{providers?.context_scope || "unknown"}</dd></div>
            <div><dt>AI model fallback</dt><dd>{providers?.remote_model_enabled ? `${providers.remote_model_provider || "configured"} enabled` : "disabled or not configured"}</dd></div>
            <div><dt>Offline mode</dt><dd>{providers?.offline_mode ? "enabled — AI model fallback calls denied" : "disabled"}</dd></div>
            <div><dt>Secure store</dt><dd>{providers?.vector_backend || "n/a"}</dd></div>
            <div><dt>Demo mode</dt><dd>{security ? (security.demo_mode ? "enabled" : "disabled") : "unknown"}</dd></div>
            <div><dt>Model cost (per 1M tokens)</dt><dd>Input: {providers?.model_input_cost_usd_per_million_tokens ?? "n/a"}</dd></div>
            <div><dt>Model cost (per 1M tokens)</dt><dd>Output: {providers?.model_output_cost_usd_per_million_tokens ?? "n/a"}</dd></div>
          </div>
          <details className="technical-details">
            <summary>Technical details</summary>
            <p>Write access is reported from the API token variable <code>WAIT_API_TOKEN</code>. Model costs are stored as <code>model_input_cost_usd_per_million_tokens</code> and <code>model_output_cost_usd_per_million_tokens</code> in USD per million tokens.</p>
          </details>
          {security?.demo_mode ? (
            <div className="panel-subsection">
              <h3>Demo mode is active.</h3>
              <p className="screen-note">Write actions and Power Platform deployment are disabled while demo mode is on, regardless of any other configuration.</p>
              <p className="screen-note">Other actions may also be unavailable when their own appliance setting is not configured — that is separate from Demo mode.</p>
              <p className="screen-note">There is no in-app switch for this. Demo mode is read when the appliance starts, so changing it requires updating the environment configuration and restarting the appliance.</p>
              <details className="technical-details">
                <summary>Technical details</summary>
                <p><code>WAIT_DEMO_MODE</code> and <code>WAIT_ALLOW_*</code> are read from the environment at startup.</p>
              </details>
            </div>
          ) : null}
        </section>

        <div className="settings-link-grid" aria-label="Appliance links">
          <Link className="settings-link-card" to="/system/appliance-health"><strong>Appliance health</strong><span>Review services, data integrity, security checks, and backups.</span></Link>
          <Link className="settings-link-card" to="/system/diagnostics"><strong>Diagnostics &amp; Support</strong><span>Prepare a local, redacted support bundle when something needs attention.</span></Link>
        </div>

        <section className="panel">
          <div className="panel-heading"><h2>Backups</h2><span>Export and restore state</span></div>
          {isAdmin ? (
            <>
              <form className="draft-form" onSubmit={createBackup}>
                <h3>Create backup</h3>
                <label>Destination<input value={backupPath} onChange={(event) => setBackupPath(event.target.value)} /></label>
                <label><input type="checkbox" checked={backupEncrypt} onChange={(event) => setBackupEncrypt(event.target.checked)} />Encrypt backup</label>
                <button type="submit">Create</button>
              </form>
              <form className="draft-form" onSubmit={restoreBackup}>
                <h3>Restore backup</h3>
                <label>Source<input value={restoreSource} onChange={(event) => setRestoreSource(event.target.value)} /></label>
                <label><input type="checkbox" checked={restoreEncrypt} onChange={(event) => setRestoreEncrypt(event.target.checked)} />Source is encrypted</label>
                <label className="switch-label"><input type="checkbox" checked={restoreAcknowledged} onChange={(event) => setRestoreAcknowledged(event.target.checked)} />I understand this replaces the current local state</label>
                <p className="screen-note">Restore replaces the appliance's current local data. Create a fresh backup first if you may need to undo this operation.</p>
                <button type="submit" disabled={!restoreSource || !restoreAcknowledged}>Restore</button>
              </form>
            </>
          ) : <p className="screen-note">Backups require administrator permissions.</p>}
        </section>
      </SettingsGroup>

      <SettingsGroup id="settings-access-heading" title="Access" description="Manage people, sign-in, roles, capabilities, and access credentials in one place.">
        <section className="panel settings-link-panel">
          <div className="panel-heading"><h2>People &amp; Access</h2><span>Operator access</span></div>
          <p className="screen-note">Manage operator accounts, Microsoft sign-in, client roles, high-impact capabilities, and access credentials.</p>
          <Link className="secondary-button" to="/settings/access">Open People &amp; Access</Link>
        </section>
      </SettingsGroup>

      <SettingsGroup id="settings-integrations-heading" title="Integrations" description="Connect optional WAIT services and install governed extension packs.">
        <section className="panel">
          <div className="panel-heading"><h2>Launch Passport</h2><span>Optional project connection</span></div>
          <RoleGate role={accessRole} allowed={["admin"]} fallback={<p className="screen-note">Only administrators can view this project connection.</p>}>
            {launchPassportState === "loading" ? <p className="screen-note">Checking connection state…</p> : null}
            {launchPassportState === "not_configured" ? (
              <div className="connection-state">
                <StatusChip status="not_configured" hint="The appliance continues to work without this optional connection." />
                <p>Launch Passport is not configured. This appliance is ready to use on its own; connect a project later when the connection service is available.</p>
                <details className="technical-details"><summary>Technical details</summary><p>The current service exposes connection status but not an in-app configuration action. It needs a configuration route before this screen can safely submit project details.</p></details>
              </div>
            ) : null}
            {launchPassportState === "available" ? (
              <div className="connection-state">
                <StatusChip status={launchPassport?.status ?? "connected"} />
                <p>Connected to project {launchPassport?.lp_project_id ?? "this project"}.</p>
                <div className="status-chip-wrap">
                  <StatusChip status={launchPassport?.token_configured ? "configured" : "not_configured"} hint={launchPassport?.token_configured ? "Project access is saved on this appliance." : "Project access needs to be added."} />
                  <StatusChip status={launchPassport?.capabilities?.launch_scan ? "available" : "upload_only"} hint={launchPassport?.capabilities?.launch_scan ? "Remote scan launch is available." : "Remote scan launch is optional and is not enabled for this project."} />
                </div>
                <details className="technical-details"><summary>Technical details</summary><p>The connection setting is stored on this appliance. Access values are never displayed here.</p></details>
              </div>
            ) : null}
            {launchPassportState === "unavailable" ? <p className="screen-note">Connection state is temporarily unavailable. Your local appliance can still be used normally.</p> : null}
          </RoleGate>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Packs</h2><span>{packs.length} installed</span></div>
          <div className="table-list">
            {packs.length === 0 ? <p>No pack entries yet.</p> : null}
            {packs.map((pack) => <div className="table-row" key={pack.name}><div><strong>{pack.name}</strong><span>v{pack.version}</span></div><em>{pack.locked ? "locked" : "unlocked"}</em><span>{pack.requires_license ? "license required" : "community"}</span></div>)}
          </div>
          {isAdmin ? <form className="draft-form" onSubmit={installPack}><h3>Install Pack</h3><label>Tarball path<input value={packPath} onChange={(event) => setPackPath(event.target.value)} /></label><button type="submit">Install</button></form> : null}
        </section>
        <div className="settings-link-grid" aria-label="Integration links">
          <Link className="settings-link-card" to="/integrations/mcp"><strong>MCP server</strong><span>Review the published tool catalog and connection details.</span></Link>
        </div>
      </SettingsGroup>

      <SettingsGroup id="settings-advanced-heading" title="Advanced" description="Read-only runtime configuration and licensing details for operators who need them.">
        <section className="panel">
          <div className="panel-heading"><h2>AI model services</h2><div className="row-actions"><span>Read-only runtime view</span>{isAdmin ? <button className="icon-button" type="button" onClick={() => void checkProviderHealth()}>Check model health</button> : null}</div></div>
          <div className="settings-list">
            {providers ? <>
              <div><dt>Local AI model</dt><dd>{providers.local_model_provider || "n/a"}</dd></div>
              <div><dt>AI model fallback</dt><dd>{providers.remote_model_enabled ? `${providers.remote_model_provider || "configured"} enabled` : "disabled or not configured"}</dd></div>
              <div><dt>Embedding service</dt><dd>{providers.embedding_provider || "n/a"}</dd></div>
              <div><dt>Embedding model</dt><dd>{providers.embedding_model || "n/a"}</dd></div>
              <div><dt>Document parser</dt><dd>{providers.document_parser || "n/a"}</dd></div>
              <div><dt>OCR</dt><dd>{providers.ocr_enabled ? "enabled" : "disabled"}</dd></div>
            </> : <p>No model service data available.</p>}
          </div>
          <details className="technical-details"><summary>Technical details</summary><div className="settings-list">{providers ? Object.entries(providers).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>) : <p>No raw configuration loaded.</p>}</div></details>
          {providerHealth ? <div className="connection-state" aria-live="polite"><strong>Model provider health</strong><span>Local: {providerHealth.local.status}{providerHealth.local.probe === "models" ? ` · ${providerHealth.local.model}` : ""}</span><span>Fallback: {providerHealth.remote.status}{providerHealth.remote.probe === "models" ? ` · ${providerHealth.remote.model}` : ""}</span><p className="screen-note">Checks use only the configured provider's documented model-list endpoint. Disabled, offline, unsupported, and unavailable states are reported without exposing credentials.</p></div> : null}
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Licensing</h2><span>Installed terms and packs</span></div>
          <div className="table-list settings-list"><div><dt>Runtime license</dt><dd>AGPL-3.0-only with WAIT additional terms</dd></div><div><dt>Attribution</dt><dd>The Powered by WAIT attribution must remain visible where the additional terms require it.</dd></div></div>
          <p className="screen-note"><a href="https://github.com/W-A-I-T/wait-local-agent/blob/main/docs/legal/community-vs-commercial-use.md" target="_blank" rel="noreferrer">Read the community and commercial use guide</a></p>
          <div className="table-list">{packs.length === 0 ? <p>No installed packs were found.</p> : null}{packs.map((pack) => <div className="table-row" key={`license-${pack.name}`}><div><strong>{pack.name}</strong><span>v{pack.version}</span></div><span>Signature record: {formatSignatureStatus(pack.signature_status)}</span></div>)}</div>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Secure store (advanced)</h2><span>{secretLoadState === "demo_unavailable" ? "unavailable in demo mode" : `${secrets.length} keys`}</span></div>
          {secretLoadState === "demo_unavailable" ? <p className="screen-note">Secure store contents are unavailable in demo mode.</p> : null}
          {secretLoadState === "unavailable" ? <p className="screen-note">Secure store contents are temporarily unavailable.</p> : null}
          <p className="screen-note">The secure store keeps credentials used by Connector Instances. Environment-backed values are configured in the server environment and require an appliance restart.</p>
          <details className="technical-details"><summary>Technical details</summary><p>The underlying vault backend is selected with <code>WAIT_SECRETS_BACKEND=fernet</code>; keys must match the exact <code>WAIT_*</code> variable name. CLI-only maintenance commands are <code>secrets init</code>, <code>migrate-external-key</code>, and <code>doctor</code>.</p></details>
          <div className="table-list">{secrets.map((secret) => <div className="table-row" key={secret.key}><div><strong>{secret.key}</strong><span>{secret.required_for}</span></div><em>{secret.configured ? "configured" : "missing"}</em></div>)}</div>
          {isAdmin ? <form className="draft-form" onSubmit={saveSecret}><h3>Add access credential</h3><label>Credential name<input autoComplete="off" list="connector-secret-names" name="secret-name" value={secretName} onChange={(event) => setSecretName(event.target.value)} /></label><datalist id="connector-secret-names">{connectorSetupEnvVarNames.map((envVar) => <option key={envVar} value={envVar} />)}</datalist><p className="field-help">For an environment-backed provider, use the exact WAIT_* name shown on Connectors. Other names remain allowed for advanced integrations.</p><label>Credential value<input autoComplete="new-password" name="new-password" type="password" value={secretValue} onChange={(event) => setSecretValue(event.target.value)} /></label><button type="submit">Save</button></form> : null}
        </section>
      </SettingsGroup>
    </section>
  );
}

function SettingsGroup({ id, title, description, children }: { id: string; title: string; description: string; children: ReactNode }) {
  return <section className="settings-group" aria-labelledby={id}><div className="settings-group-heading"><p className="eyebrow">Settings</p><h2 id={id}>{title}</h2><p className="screen-note">{description}</p></div>{children}</section>;
}

function formatSignatureStatus(status: string | undefined): string {
  if (!status) return "Not recorded";
  const readable = status.replaceAll("_", " ");
  return `${readable.charAt(0).toUpperCase()}${readable.slice(1)}`;
}

function isLaunchPassportNotConfigured(error: unknown): boolean {
  return error instanceof ApiRequestError
    && (error.status === 409 || /not configured/i.test(`${error.message} ${error.technicalDetail}`));
}

function isDemoModeSecretsUnavailable(error: unknown, security: SecuritySettings): boolean {
  return security.demo_mode === true && error instanceof ApiRequestError && error.status === 403;
}
