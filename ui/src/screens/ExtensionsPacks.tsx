import { useCallback, useEffect, useMemo, useState } from "react";
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

  return (
    <div className="screen-stack">
      <section className="panel" aria-busy={loading}>
        <div className="panel-heading">
          <div>
            <p className="eyebrow">System</p>
            <h2>Extensions / Packs</h2>
            <p className="screen-note">Read-only inventory of installed packs, trust state, licensing, and mounted interfaces.</p>
          </div>
          <button className="icon-button" type="button" onClick={() => void refresh()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {error ? <div className="notice danger" role="alert">{error}</div> : null}
        {loading ? <p className="screen-note">Loading installed extension and pack details…</p> : null}
        {!loading && !error && rows.length === 0 ? <p className="screen-note">No packs are installed on this appliance.</p> : null}
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
