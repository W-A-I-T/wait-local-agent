import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import type { PackInfo, PackStatus } from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { StatusChip } from "../components/StatusChip";

type PackRow = {
  summary: PackInfo;
  status?: PackStatus;
};

export function ExtensionsPacks() {
  const { isAdmin, role, roleResolved } = useDashboard();
  const accessRole = role ?? (isAdmin ? "admin" : "viewer");
  const canView = roleResolved && isAdmin;
  const fallback = (
    <section className="panel">
      <div className="panel-heading">
        <h2>Extensions / Packs</h2>
        <span>System</span>
      </div>
      <p className="screen-note">
        {roleResolved
          ? "Administrator role required to view installed extensions and packs."
          : "Checking administrator access before loading installed extensions and packs."}
      </p>
    </section>
  );

  return (
    <RoleGate role={accessRole} resolved={roleResolved} allowed={["admin"]} fallback={fallback}>
      <ExtensionsPacksContent canView={canView} />
    </RoleGate>
  );
}

function ExtensionsPacksContent({ canView }: { canView: boolean }) {
  const [packs, setPacks] = useState<PackInfo[]>([]);
  const [statuses, setStatuses] = useState<PackStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [packPath, setPackPath] = useState("");
  const [packLicense, setPackLicense] = useState("");
  const [installing, setInstalling] = useState(false);
  const [installStatus, setInstallStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [packRows, statusRows] = await Promise.all([
        apiFetch<PackInfo[]>("/packs"),
        apiFetch<PackStatus[]>("/packs/status")
      ]);
      setPacks(Array.isArray(packRows) ? packRows : []);
      setStatuses(Array.isArray(statusRows) ? statusRows : []);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load extension and pack details.");
      setPacks([]);
      setStatuses([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canView) {
      void refresh();
    }
  }, [canView, refresh]);

  const rows = useMemo<PackRow[]>(() => {
    const statusByName = new Map(statuses.map((status) => [status.name, status]));
    return packs.map((summary) => ({ summary, status: statusByName.get(summary.name) }));
  }, [packs, statuses]);

  const installPack = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!packPath.trim()) {
      setInstallStatus({ kind: "error", message: "Set a pack tarball path first." });
      return;
    }
    setInstalling(true);
    setInstallStatus(null);
    try {
      const body = await apiFetch<Record<string, string | number | boolean | null>>("/packs/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tarball_path: packPath, license_key: packLicense || undefined })
      });
      setInstallStatus({
        kind: "success",
        message: `Pack installed: ${(body as { pack_name?: string }).pack_name || "done"}.`
      });
      await refresh();
      setPackPath("");
      setPackLicense("");
    } catch (requestError) {
      setInstallStatus({ kind: "error", message: requestError instanceof Error ? requestError.message : "Install failed." });
    } finally {
      setInstalling(false);
    }
  }, [packLicense, packPath, refresh]);

  return (
    <div className="screen-stack">
      <section className="panel" aria-busy={loading}>
        <div className="panel-heading">
          <div>
            <p className="eyebrow">System</p>
            <h2>Extensions / Packs</h2>
            <p className="screen-note">Manage installed packs, trust state, licensing, and mounted interfaces.</p>
          </div>
          <button className="icon-button" type="button" onClick={() => void refresh()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {error ? <div className="notice danger" role="alert">{error}</div> : null}
        {installStatus ? <div className={`notice ${installStatus.kind === "error" ? "danger" : "success"}`} role={installStatus.kind === "error" ? "alert" : "status"}>{installStatus.message}</div> : null}
        {loading ? <p className="screen-note">Loading installed extension and pack details…</p> : null}
        {!loading && !error && rows.length === 0 ? <p className="screen-note">No packs are installed on this appliance.</p> : null}
      </section>

      <section className="panel" aria-labelledby="pack-install-heading">
        <div className="panel-heading">
          <div>
            <h2 id="pack-install-heading">Install pack</h2>
            <span>Administrator action</span>
          </div>
        </div>
        <form className="draft-form" onSubmit={(event) => void installPack(event)}>
          <label>
            Tarball path
            <input value={packPath} disabled={installing} onChange={(event) => setPackPath(event.target.value)} />
          </label>
          <label>
            License key
            <input value={packLicense} disabled={installing} onChange={(event) => setPackLicense(event.target.value)} />
          </label>
          <button type="submit" disabled={installing}>{installing ? "Installing…" : "Install pack"}</button>
        </form>
      </section>

      {!loading && !error && rows.length > 0 ? (
        <section className="panel">
          <div className="panel-heading">
            <h2>Installed packs</h2>
            <span>{rows.length} installed</span>
          </div>
          <div className="pack-list">
            {rows.map(({ summary, status }) => <PackCard key={summary.name} summary={summary} status={status} />)}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function PackCard({ summary, status }: PackRow) {
  const locked = status?.locked ?? summary.locked;
  const requiresLicense = status?.requires_license ?? summary.requires_license;

  return (
    <article className="pack-card">
      <div className="pack-card-heading">
        <div>
          <h3>{summary.name}</h3>
          <p className="screen-note">Version {status?.version ?? summary.version}</p>
        </div>
        <div className="pack-badges" aria-label={`${summary.name} status`}>
          <StatusChip status={locked ? "locked" : "unlocked"} hint="Lock state reported by the appliance." />
          <StatusChip status={requiresLicense ? "license_required" : "license_not_required"} />
        </div>
      </div>

      {status ? (
        <dl className="pack-detail-grid">
          <Detail label="Name" value={status.name} />
          <Detail label="Version" value={status.version} />
          <Detail label="Locked" value={formatBoolean(status.locked)} />
          <Detail label="Requires license" value={formatBoolean(status.requires_license)} />
          <Detail label="CLI available" value={formatBoolean(status.cli_available)} />
          <Detail label="Router available" value={formatBoolean(status.router_available)} />
          <Detail label="CLI mounted" value={formatBoolean(status.mounted_cli)} />
          <Detail label="Router mounted" value={formatBoolean(status.mounted_router)} />
          <Detail label="Error" value={status.error || "None"} />
        </dl>
      ) : (
        <p className="screen-note">Detailed runtime status was not reported for this pack.</p>
      )}
    </article>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function formatBoolean(value: boolean): string {
  return value ? "Yes" : "No";
}
