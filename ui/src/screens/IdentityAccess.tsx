import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";

type ClientRole = "end_user" | "viewer" | "technician" | "admin";

type CredentialSummary = {
  fingerprint: string;
  active: boolean;
  created_at: string;
};

type Principal = {
  principal_id: string;
  kind: "customer" | "staff";
  display_name: string;
  active: boolean;
  client_roles: Array<[string, ClientRole]>;
  global_roles: string[];
  credentials: CredentialSummary[];
};

type PrincipalCredentialResponse = {
  principal: Principal;
  credential: string | null;
  credential_notice: string;
};

const roles: ClientRole[] = ["viewer", "technician", "admin", "end_user"];

export function IdentityAccess() {
  const { clients } = useDashboard();
  const [principals, setPrincipals] = useState<Principal[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [issuedCredential, setIssuedCredential] = useState("");
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<"staff" | "customer">("staff");
  const [newClientId, setNewClientId] = useState("");
  const [newRole, setNewRole] = useState<ClientRole | "">("");
  const [newMspAdmin, setNewMspAdmin] = useState(false);
  const [membershipClientId, setMembershipClientId] = useState("");
  const [membershipRole, setMembershipRole] = useState<ClientRole | "">("");

  const selected = useMemo(
    () => principals.find((principal) => principal.principal_id === selectedId) ?? null,
    [principals, selectedId]
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiFetch<Principal[]>("/packs/operator-control/principals");
      if (!Array.isArray(rows)) throw new Error("The appliance returned invalid principal data.");
      setPrincipals(rows);
      setSelectedId((current) => rows.some((row) => row.principal_id === current) ? current : rows[0]?.principal_id ?? "");
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load operator identities.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createPrincipal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newId.trim()) return;
    if ((newClientId && !newRole) || (!newMspAdmin && (!newClientId || !newRole))) {
      setMessage("Choose an initial client and role, or grant MSP administrator access.");
      return;
    }
    setBusy(true);
    setIssuedCredential("");
    try {
      const response = await apiFetch<PrincipalCredentialResponse>("/packs/operator-control/principals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          principal_id: newId.trim(),
          kind: newKind,
          display_name: newName.trim(),
          client_roles: newClientId && newRole ? [{ client_id: newClientId, role: newRole }] : [],
          msp_admin: newKind === "staff" && newMspAdmin,
          issue_credential: true
        })
      });
      setIssuedCredential(response.credential ?? "");
      setNewId("");
      setNewName("");
      setMessage(response.credential_notice);
      await refresh();
      setSelectedId(response.principal.principal_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create the principal.");
    } finally {
      setBusy(false);
    }
  }

  async function mutate(path: string, init: RequestInit, success: string) {
    setBusy(true);
    setIssuedCredential("");
    try {
      const row = await apiFetch<Principal>(path, init);
      setPrincipals((current) => current.map((item) => item.principal_id === row.principal_id ? row : item));
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The identity change failed.");
    } finally {
      setBusy(false);
    }
  }

  async function rotateCredential() {
    if (!selected) return;
    setBusy(true);
    setIssuedCredential("");
    try {
      const response = await apiFetch<PrincipalCredentialResponse>(
        `/packs/operator-control/principals/${encodeURIComponent(selected.principal_id)}/credentials/rotate`,
        { method: "POST" }
      );
      setPrincipals((current) => current.map((item) => item.principal_id === response.principal.principal_id ? response.principal : item));
      setIssuedCredential(response.credential ?? "");
      setMessage(response.credential_notice);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Credential rotation failed.");
    } finally {
      setBusy(false);
    }
  }

  async function addMembership(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !membershipClientId || !membershipRole) return;
    await mutate(
      `/packs/operator-control/principals/${encodeURIComponent(selected.principal_id)}/client-roles/${encodeURIComponent(membershipClientId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: membershipRole })
      },
      "Client role saved."
    );
  }

  async function copyCredential() {
    if (!issuedCredential || !navigator.clipboard) return;
    await navigator.clipboard.writeText(issuedCredential);
    setMessage("Credential copied. It will not be shown again after you leave this page.");
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Authorization</p>
            <h2>Identity &amp; Access</h2>
            <p className="screen-note">Create local principals, issue or rotate one-time credentials, and manage exact client roles. Credentials are hashed before persistence.</p>
          </div>
          <button type="button" onClick={() => void refresh()} disabled={loading || busy}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
        {message ? <div className="notice" role="status">{message}</div> : null}
        {issuedCredential ? (
          <div className="notice" role="alert">
            <strong>One-time credential</strong>
            <p>Store this now. WAIT will not display it again.</p>
            <code>{issuedCredential}</code>
            <button type="button" onClick={() => void copyCredential()}>Copy credential</button>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Create principal</h2><span>MSP operator only</span></div>
        <form className="draft-form" onSubmit={(event) => void createPrincipal(event)}>
          <div className="grid">
            <label>Principal ID<input value={newId} onChange={(event) => setNewId(event.target.value)} placeholder="tech-jane" /></label>
            <label>Display name<input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="Jane Technician" /></label>
            <label>Kind<select value={newKind} onChange={(event) => {
              const kind = event.target.value as "staff" | "customer";
              setNewKind(kind);
              if (kind === "customer") setNewMspAdmin(false);
            }}><option value="staff">Staff</option><option value="customer">Customer</option></select></label>
            <label>Initial client<select value={newClientId} onChange={(event) => setNewClientId(event.target.value)}>
              <option value="">No client role</option>
              {clients.map((client) => <option key={client.client_id} value={client.client_id}>{client.name}</option>)}
            </select></label>
            <label>Initial role<select value={newRole} onChange={(event) => setNewRole(event.target.value as ClientRole | "")}>
              <option value="">Choose a role</option>
              {roles.map((role) => <option key={role} value={role}>{role}</option>)}
            </select></label>
            <label><input type="checkbox" checked={newMspAdmin} disabled={newKind === "customer"} onChange={(event) => setNewMspAdmin(event.target.checked)} /> MSP administrator</label>
          </div>
          <button type="submit" disabled={busy || !newId.trim() || (newClientId && !newRole) || (!newMspAdmin && (!newClientId || !newRole))}>{busy ? "Saving…" : "Create & issue credential"}</button>
        </form>
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Principals</h2><span>{principals.length} configured</span></div>
        {loading ? <LoadingState label="Loading identities…" /> : principals.length === 0 ? <EmptyState title="No database principals" why="Create the first staff or customer principal above. Bootstrap tokens remain separate recovery credentials." /> : (
          <div className="grid">
            <label>Principal<select value={selectedId} onChange={(event) => { setSelectedId(event.target.value); setIssuedCredential(""); }}>
              {principals.map((principal) => <option key={principal.principal_id} value={principal.principal_id}>{principal.display_name || principal.principal_id} · {principal.active ? "active" : "inactive"}</option>)}
            </select></label>
          </div>
        )}
      </section>

      {selected ? (
        <>
          <section className="panel">
            <div className="panel-heading">
              <div><h2>{selected.display_name || selected.principal_id}</h2><span>{selected.kind} · {selected.active ? "active" : "inactive"}</span></div>
              <span>{selected.global_roles.includes("msp_admin") ? "MSP administrator" : "Client scoped"}</span>
            </div>
            <div className="designer-actions">
              <button type="button" disabled={busy || !selected.active} onClick={() => void rotateCredential()}>Rotate credential</button>
              <button type="button" disabled={busy || !selected.active} onClick={() => {
                if (window.confirm(`Revoke all credentials for ${selected.principal_id}?`)) {
                  void mutate(`/packs/operator-control/principals/${encodeURIComponent(selected.principal_id)}/credentials/revoke-all`, { method: "POST" }, "All credentials revoked.");
                }
              }}>Revoke credentials</button>
              <button type="button" disabled={busy} onClick={() => {
                const nextActive = !selected.active;
                if (!nextActive && !window.confirm(`Deactivate ${selected.principal_id}? Existing credentials will be revoked.`)) return;
                void mutate(
                  `/packs/operator-control/principals/${encodeURIComponent(selected.principal_id)}`,
                  { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: nextActive }) },
                  nextActive ? "Principal reactivated. Rotate a credential before sign-in." : "Principal deactivated."
                );
              }}>{selected.active ? "Deactivate" : "Reactivate"}</button>
              {selected.kind === "staff" ? <button type="button" disabled={busy} onClick={() => {
                const enabled = !selected.global_roles.includes("msp_admin");
                if (!enabled && !window.confirm(`Remove MSP administrator from ${selected.principal_id}?`)) return;
                void mutate(
                  `/packs/operator-control/principals/${encodeURIComponent(selected.principal_id)}/msp-admin`,
                  { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) },
                  enabled ? "MSP administrator granted." : "MSP administrator removed."
                );
              }}>{selected.global_roles.includes("msp_admin") ? "Remove MSP admin" : "Grant MSP admin"}</button> : null}
            </div>
          </section>

          <section className="designer-grid">
            <div className="panel">
              <div className="panel-heading"><h2>Client roles</h2><span>{selected.client_roles.length}</span></div>
              {selected.client_roles.length === 0 ? <p className="screen-note">No client-specific roles.</p> : <div className="event-list">
                {selected.client_roles.map(([clientId, role]) => (
                  <article className="event-row" key={clientId}>
                    <div><strong>{clientId}</strong><small>{role}</small></div>
                    <button type="button" disabled={busy} onClick={() => {
                      if (window.confirm(`Remove ${selected.principal_id} from ${clientId}?`)) {
                        void mutate(
                          `/packs/operator-control/principals/${encodeURIComponent(selected.principal_id)}/client-roles/${encodeURIComponent(clientId)}`,
                          { method: "DELETE" },
                          "Client role removed."
                        );
                      }
                    }}>Remove</button>
                  </article>
                ))}
              </div>}
              <form onSubmit={(event) => void addMembership(event)}>
                <label>Client<select value={membershipClientId} onChange={(event) => setMembershipClientId(event.target.value)}>{clients.map((client) => <option key={client.client_id} value={client.client_id}>{client.name}</option>)}</select></label>
                <label>Role<select value={membershipRole} onChange={(event) => setMembershipRole(event.target.value as ClientRole | "")}>
                  <option value="">Choose a role</option>
                  {roles.map((role) => <option key={role} value={role}>{role}</option>)}
                </select></label>
                <button type="submit" disabled={busy || !membershipClientId || !membershipRole}>Add / update role</button>
              </form>
            </div>

            <div className="panel">
              <div className="panel-heading"><h2>Credential metadata</h2><span>{selected.credentials.filter((credential) => credential.active).length} active</span></div>
              {selected.credentials.length === 0 ? <p className="screen-note">No credential has been issued.</p> : <div className="event-list">
                {selected.credentials.map((credential) => (
                  <article className="event-row" key={`${credential.fingerprint}-${credential.created_at}`}>
                    <div><strong>{credential.fingerprint}</strong><small>{credential.created_at}</small></div>
                    <span>{credential.active ? "active" : "revoked"}</span>
                  </article>
                ))}
              </div>}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
