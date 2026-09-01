import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";

type ClientRole = "end_user" | "viewer" | "technician" | "admin";

type PrincipalCredential = {
  credential_hash_prefix: string;
  active: boolean;
  created_at: string;
};

type Principal = {
  principal_id: string;
  kind: "customer" | "staff";
  display_name: string;
  active: boolean;
  created_at: string;
  client_roles: Array<[string, ClientRole]>;
  global_roles: string[];
  credential_count: number;
  credentials: PrincipalCredential[];
};

type Notice = { kind: "success" | "danger"; message: string } | null;

const roleLabels: Record<ClientRole, string> = {
  end_user: "End user",
  viewer: "Viewer",
  technician: "Technician",
  admin: "Administrator"
};

export function PrincipalsAdmin() {
  const { clients } = useDashboard();
  const [principals, setPrincipals] = useState<Principal[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [newPrincipalId, setNewPrincipalId] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newKind, setNewKind] = useState<"staff" | "customer">("staff");
  const [role, setRole] = useState<ClientRole>("technician");
  const [clientId, setClientId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [oneTimeToken, setOneTimeToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async (clearNotice = true) => {
    setLoading(true);
    if (clearNotice) setNotice(null);
    try {
      const rows = await apiFetch<Principal[]>("/auth/principals");
      const next = Array.isArray(rows) ? rows : [];
      setPrincipals(next);
      setSelectedId((current) => next.some((principal) => principal.principal_id === current) ? current : (next[0]?.principal_id ?? ""));
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "People and access data could not be loaded." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!clientId && clients[0]) setClientId(clients[0].client_id);
  }, [clientId, clients]);

  const selected = useMemo(
    () => principals.find((principal) => principal.principal_id === selectedId) ?? null,
    [principals, selectedId]
  );

  async function submitCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newPrincipalId.trim() || !newDisplayName.trim()) return;
    setBusy(true);
    setNotice(null);
    try {
      await apiFetch<Principal>("/auth/principals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ principal_id: newPrincipalId, kind: newKind, display_name: newDisplayName })
      });
      setNewPrincipalId("");
      setNewDisplayName("");
      await refresh(false);
      setNotice({ kind: "success", message: "Principal created." });
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "Principal could not be created." });
    } finally {
      setBusy(false);
    }
  }

  async function updatePrincipal(active: boolean) {
    if (!selected) return;
    setBusy(true);
    setNotice(null);
    try {
      await apiFetch<Principal>(`/auth/principals/${encodeURIComponent(selected.principal_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active })
      });
      await refresh(false);
      setNotice({ kind: "success", message: active ? "Principal activated." : "Principal deactivated." });
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "Principal status could not be changed." });
    } finally {
      setBusy(false);
    }
  }

  async function issueCredential() {
    if (!selected) return;
    setBusy(true);
    setNotice(null);
    setCopied(false);
    try {
      const response = await apiFetch<{ token: string }>(`/auth/principals/${encodeURIComponent(selected.principal_id)}/credentials`, { method: "POST" });
      setOneTimeToken(response.token);
      await refresh(false);
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "Credential could not be issued." });
    } finally {
      setBusy(false);
    }
  }

  async function revokeCredential(credential: PrincipalCredential) {
    if (!selected || !credential.active) return;
    setBusy(true);
    setNotice(null);
    try {
      await apiFetch(`/auth/principals/${encodeURIComponent(selected.principal_id)}/credentials/revoke`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential_hash: credential.credential_hash_prefix })
      });
      await refresh(false);
      setNotice({ kind: "success", message: "Credential revoked." });
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "Credential could not be revoked." });
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(method: "POST" | "DELETE", globalRole = false, requestedClientId = clientId, requestedRole = role) {
    if (!selected || (!globalRole && !requestedClientId)) return;
    setBusy(true);
    setNotice(null);
    const path = globalRole
      ? `/auth/principals/${encodeURIComponent(selected.principal_id)}/global-roles`
      : `/auth/principals/${encodeURIComponent(selected.principal_id)}/client-roles`;
    try {
      await apiFetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(globalRole ? { role: "msp_admin" } : { client_id: requestedClientId, role: requestedRole })
      });
      await refresh(false);
      setNotice({ kind: "success", message: method === "POST" ? "Role added." : "Role removed." });
    } catch (error) {
      setNotice({ kind: "danger", message: error instanceof Error ? error.message : "Role change failed." });
    } finally {
      setBusy(false);
    }
  }

  async function copyToken() {
    if (!oneTimeToken || !navigator.clipboard) return;
    await navigator.clipboard.writeText(oneTimeToken);
    setCopied(true);
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Authorization</p>
            <h2>People &amp; Access</h2>
            <p className="screen-note">Create technician and viewer identities, manage roles, and issue or revoke bearer credentials.</p>
          </div>
          <button type="button" onClick={() => void refresh()} disabled={loading || busy}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
      </section>

      {notice ? <div className={`notice ${notice.kind}`} role={notice.kind === "danger" ? "alert" : "status"}>{notice.message}</div> : null}

      <section className="panel" aria-labelledby="create-principal-heading">
        <div className="panel-heading"><h3 id="create-principal-heading">Create principal</h3></div>
        <form onSubmit={(event) => void submitCreate(event)}>
          <label htmlFor="principal-id">Principal ID</label>
          <input id="principal-id" value={newPrincipalId} onChange={(event) => setNewPrincipalId(event.target.value)} disabled={busy} required />
          <label htmlFor="principal-name">Display name</label>
          <input id="principal-name" value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} disabled={busy} required />
          <label htmlFor="principal-kind">Kind</label>
          <select id="principal-kind" value={newKind} onChange={(event) => setNewKind(event.target.value as "staff" | "customer")} disabled={busy}>
            <option value="staff">Staff</option>
            <option value="customer">Customer</option>
          </select>
          <button type="submit" disabled={busy || !newPrincipalId.trim() || !newDisplayName.trim()}>Create principal</button>
        </form>
      </section>

      {loading ? <LoadingState label="Loading principals…" /> : principals.length === 0 ? (
        <EmptyState title="No principals yet" why="Create the first staff or customer identity to manage access." />
      ) : (
        <section className="panel" aria-labelledby="principal-list-heading">
          <div className="panel-heading"><div><h3 id="principal-list-heading">Principals</h3><span>{principals.length} principal(s)</span></div></div>
          <div className="event-list">
            {principals.map((principal) => (
              <article className="event-row" key={principal.principal_id}>
                <div>
                  <strong>{principal.display_name}</strong>
                  <small>{principal.principal_id} · {principal.kind} · {principal.active ? "Active" : "Inactive"}</small>
                  <small>{principal.credential_count} credential(s) · {principal.client_roles.length} client role(s)</small>
                </div>
                <button type="button" onClick={() => setSelectedId(principal.principal_id)} disabled={busy}>{selectedId === principal.principal_id ? "Selected" : "Manage"}</button>
              </article>
            ))}
          </div>
        </section>
      )}

      {selected ? (
        <aside className="panel" aria-label="Principal details">
          <div className="panel-heading">
            <div><p className="eyebrow">Principal details</p><h3>{selected.display_name}</h3><span>{selected.principal_id}</span></div>
            <button type="button" onClick={() => void updatePrincipal(!selected.active)} disabled={busy}>{selected.active ? "Deactivate" : "Activate"}</button>
          </div>
          <p className="screen-note">Status: {selected.active ? "Active" : "Inactive"}. Deactivating preserves audit history and disables its credentials.</p>

          <section aria-labelledby="principal-roles-heading">
            <h4 id="principal-roles-heading">Roles</h4>
            {selected.global_roles.length ? <p>Global: {selected.global_roles.join(", ")}</p> : <p className="screen-note">No global roles.</p>}
            <ul>
              {selected.client_roles.map(([assignedClientId, assignedRole]) => <li key={`${assignedClientId}:${assignedRole}`}>{assignedClientId} · {roleLabels[assignedRole]} <button type="button" onClick={() => void changeRole("DELETE", false, assignedClientId, assignedRole)} disabled={busy}>Remove</button></li>)}
            </ul>
            <label htmlFor="role-client">Client</label>
            <select id="role-client" value={clientId} onChange={(event) => setClientId(event.target.value)} disabled={busy}>
              <option value="">Select a client</option>
              {clients.map((client) => <option key={client.client_id} value={client.client_id}>{client.name}</option>)}
            </select>
            <label htmlFor="role-kind">Client role</label>
            <select id="role-kind" value={role} onChange={(event) => setRole(event.target.value as ClientRole)} disabled={busy}>
              {Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <button type="button" onClick={() => void changeRole("POST")} disabled={busy || !clientId}>Add client role</button>
            {selected.global_roles.includes("msp_admin") ? (
              <button type="button" onClick={() => void changeRole("DELETE", true)} disabled={busy}>Remove MSP administrator role</button>
            ) : (
              <button type="button" onClick={() => void changeRole("POST", true)} disabled={busy}>Add MSP administrator role</button>
            )}
          </section>

          <section aria-labelledby="principal-credentials-heading">
            <div className="panel-heading"><h4 id="principal-credentials-heading">Credentials</h4><button type="button" onClick={() => void issueCredential()} disabled={busy || !selected.active}>Issue credential</button></div>
            {selected.credentials.length ? <ul>{selected.credentials.map((credential) => <li key={credential.credential_hash_prefix}>{credential.credential_hash_prefix}… · {credential.active ? "Active" : "Revoked"} {credential.active ? <button type="button" onClick={() => void revokeCredential(credential)} disabled={busy}>Revoke</button> : null}</li>)}</ul> : <p className="screen-note">No credentials issued.</p>}
          </section>
          <Link to="/microsoft-admin/access">Manage Microsoft Admin capability grants</Link>
        </aside>
      ) : null}

      {oneTimeToken ? (
        <div className="panel" role="dialog" aria-labelledby="one-time-token-heading">
          <h3 id="one-time-token-heading">Credential issued</h3>
          <p className="screen-note">This bearer token is shown once. Copy it now; it cannot be retrieved later.</p>
          <code>{oneTimeToken}</code>
          <div><button type="button" onClick={() => void copyToken()}>{copied ? "Copied" : "Copy token"}</button><button type="button" onClick={() => { setOneTimeToken(null); setCopied(false); }}>Close</button></div>
        </div>
      ) : null}
    </div>
  );
}
