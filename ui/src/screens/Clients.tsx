import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import type { ClientDirectoryEntry } from "../api/types";
import { StatusChip } from "../components/StatusChip";

export function Clients() {
  const [clients, setClients] = useState<ClientDirectoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadClients = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch<ClientDirectoryEntry[]>("/clients");
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned invalid Clients data.");
      }
      setClients(result.filter((client) => client.client_id !== "__quarantine__"));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Clients.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadClients();
  }, [loadClients]);

  return (
    <div className="screen-stack">
      <section className="panel clients-hero">
        <div>
          <p className="eyebrow">Directory</p>
          <h2>Clients</h2>
          <p className="screen-note">Review the clients available in this workspace. This screen is read-only.</p>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadClients()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </section>

      {error ? (
        <div className="notice danger" role="alert">
          <span>{error}</span>
          <button className="secondary-button" type="button" onClick={() => void loadClients()} disabled={loading}>Try again</button>
        </div>
      ) : null}

      {loading ? (
        <section className="panel" aria-busy="true">
          <p className="screen-note">Loading Clients…</p>
        </section>
      ) : clients.length === 0 ? (
        <section className="panel empty-state">
          <h3>No clients are visible.</h3>
          <p>The appliance has not returned any clients for this scope.</p>
        </section>
      ) : (
        <section className="panel" aria-labelledby="clients-list-heading">
          <div className="panel-heading">
            <div>
              <h2 id="clients-list-heading">Client directory</h2>
              <span>{clients.length} client{clients.length === 1 ? "" : "s"}</span>
            </div>
            <span>Viewer access</span>
          </div>
          <div className="clients-table-wrap">
            <table className="clients-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Client ID</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {clients.map((client) => (
                  <tr key={client.client_id}>
                    <td><strong>{client.name}</strong></td>
                    <td><code>{client.client_id}</code></td>
                    <td><StatusChip status={client.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
