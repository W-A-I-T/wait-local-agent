import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { type PackInfo, type ProviderSettings, type SecretRecord, type SecuritySettings, type UpdateStatus } from "../api/types";

export function Settings() {
  const { isAdmin } = useDashboard();
  const [providers, setProviders] = useState<ProviderSettings | null>(null);
  const [security, setSecurity] = useState<SecuritySettings | null>(null);
  const [packs, setPacks] = useState<PackInfo[]>([]);
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [statusMessage, setStatusMessage] = useState("");

  const [packPath, setPackPath] = useState("");
  const [packLicense, setPackLicense] = useState("");
  const [secretName, setSecretName] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [backupPath, setBackupPath] = useState("");
  const [backupEncrypt, setBackupEncrypt] = useState(false);
  const [restoreSource, setRestoreSource] = useState("");
  const [restoreEncrypt, setRestoreEncrypt] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [providerRows, securityRows, packRows, secretRows, updateRows] = await Promise.all([
        apiFetch<ProviderSettings>("/settings/providers"),
        apiFetch<SecuritySettings>("/settings/security"),
        apiFetch<PackInfo[]>("/packs"),
        apiFetch<SecretRecord[]>("/secrets"),
        apiFetch<UpdateStatus>("/update-status")
      ]);
      setProviders(providerRows);
      setSecurity(securityRows);
      setPacks(packRows);
      setSecrets(secretRows);
      setStatus(updateRows);
      setStatusMessage("Settings loaded.");
    } catch (error) {
      if (error instanceof Error && /403/.test(error.message)) {
        setStatusMessage("Insufficient role for admin settings.");
        return;
      }
      setStatusMessage(error instanceof Error ? error.message : "Unable to load settings.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
        body: JSON.stringify({ tarball_path: packPath, license_key: packLicense || undefined })
      });
      setStatusMessage(`Pack installed: ${(body as { pack_name?: string }).pack_name || "done"}.`);
      await refresh();
      setPackPath("");
      setPackLicense("");
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
      const value = await apiFetch<UpdateStatus>("/update-check");
      setStatus(value);
      setStatusMessage("Update check complete.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Update check failed.");
    }
  }

  return (
    <section className="screen-stack">
      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Admin Settings</h2>
          <span>{isAdmin ? "admin mode" : "viewer mode"}</span>
        </div>
        <div className="row-actions">
          <Link className="icon-button" to="/?onboarding=1">Launch onboarding</Link>
          {isAdmin ? <button className="icon-button" type="button" onClick={() => void checkForUpdates()}>Check for updates</button> : null}
        </div>

        {statusMessage ? <div className="notice">{statusMessage}</div> : null}
        {!isAdmin ? <div className="notice danger">Administrator role required for write controls.</div> : null}

        <div className="table-list settings-list">
          <div>
            <dt>Write health</dt>
            <dd>{security?.api_token_configured ? "API token saved" : "No API token"}</dd>
          </div>
          <div>
            <dt>Update check</dt>
            <dd>{status?.status || "idle"}</dd>
          </div>
          <div>
            <dt>Provider mode</dt>
            <dd>{providers?.local_model_provider || "n/a"}</dd>
          </div>
          <div>
            <dt>Secret manager</dt>
            <dd>{providers?.vector_backend || "n/a"}</dd>
          </div>
          <div>
            <dt>Demo mode</dt>
            <dd>{security ? (security.demo_mode ? "enabled" : "disabled") : "unknown"}</dd>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Providers</h2>
          <span>runtime stack</span>
        </div>
        <div className="settings-list">
          {providers ? (
            Object.entries(providers).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))
          ) : <p>No provider data available.</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Packs</h2>
          <span>{packs.length} installed</span>
        </div>
        <div className="table-list">
          {packs.length === 0 ? <p>No pack entries yet.</p> : null}
          {packs.map((pack) => (
            <div className="table-row" key={pack.name}>
              <div>
                <strong>{pack.name}</strong>
                <span>v{pack.version}</span>
              </div>
              <em>{pack.locked ? "locked" : "unlocked"}</em>
              <span>{pack.requires_license ? "license required" : "community"}</span>
            </div>
          ))}
        </div>

        {isAdmin ? (
          <form className="draft-form" onSubmit={installPack}>
            <h3>Install Pack</h3>
            <label>
              Tarball path
              <input value={packPath} onChange={(event) => setPackPath(event.target.value)} />
            </label>
            <label>
              License key
              <input value={packLicense} onChange={(event) => setPackLicense(event.target.value)} />
            </label>
            <button type="submit">Install</button>
          </form>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Backups</h2>
          <span>Export and restore state</span>
        </div>
        {isAdmin ? (
          <>
            <form className="draft-form" onSubmit={createBackup}>
              <h3>Create backup</h3>
              <label>
                Destination
                <input value={backupPath} onChange={(event) => setBackupPath(event.target.value)} />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={backupEncrypt}
                  onChange={(event) => setBackupEncrypt(event.target.checked)}
                />
                Encrypt backup
              </label>
              <button type="submit">Create</button>
            </form>

            <form className="draft-form" onSubmit={restoreBackup}>
              <h3>Restore backup</h3>
              <label>
                Source
                <input value={restoreSource} onChange={(event) => setRestoreSource(event.target.value)} />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={restoreEncrypt}
                  onChange={(event) => setRestoreEncrypt(event.target.checked)}
                />
                Source is encrypted
              </label>
              <button type="submit">Restore</button>
            </form>
          </>
        ) : <p className="screen-note">Backups require admin permissions.</p>}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Secrets</h2>
          <span>{secrets.length} keys</span>
        </div>
        <div className="table-list">
          {secrets.map((secret) => (
            <div className="table-row" key={secret.key}>
              <div><strong>{secret.key}</strong><span>{secret.required_for}</span></div>
              <em>{secret.configured ? "configured" : "missing"}</em>
            </div>
          ))}
        </div>

        {isAdmin ? (
          <form className="draft-form" onSubmit={saveSecret}>
            <h3>Add secret</h3>
            <label>
              Secret name
              <input value={secretName} onChange={(event) => setSecretName(event.target.value)} />
            </label>
            <label>
              Secret value
              <input type="password" value={secretValue} onChange={(event) => setSecretValue(event.target.value)} />
            </label>
            <button type="submit">Save</button>
          </form>
        ) : null}
      </section>
    </section>
  );
}
