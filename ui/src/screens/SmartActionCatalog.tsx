import { useEffect, useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { apiFetch } from "../api/client";
import type { SmartActionManifest } from "../api/types";
import { StatusChip } from "../components/StatusChip";

type ApprovalFilter = "all" | "required" | "not-required";

export function SmartActionCatalog() {
  const [actions, setActions] = useState<SmartActionManifest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [riskFilter, setRiskFilter] = useState("all");
  const [approvalFilter, setApprovalFilter] = useState<ApprovalFilter>("all");
  const [roleFilter, setRoleFilter] = useState("all");
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null);

  async function loadActions() {
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch<SmartActionManifest[]>("/smart-actions");
      if (!Array.isArray(result)) {
        throw new Error("The appliance returned an invalid Smart Action catalog.");
      }
      setActions(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load Smart Actions.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadActions();
  }, []);

  const riskOptions = useMemo(() => uniqueValues(actions.map((action) => action.risk_level)), [actions]);
  const roleOptions = useMemo(() => uniqueValues(actions.map((action) => action.required_role)), [actions]);
  const filteredActions = useMemo(() => {
    const query = search.trim().toLowerCase();
    return actions.filter((action) => {
      const matchesSearch = !query || [action.action_id, action.title, action.description]
        .some((value) => value.toLowerCase().includes(query));
      const matchesRisk = riskFilter === "all" || action.risk_level === riskFilter;
      const matchesApproval = approvalFilter === "all"
        || (approvalFilter === "required" && action.requires_approval)
        || (approvalFilter === "not-required" && !action.requires_approval);
      const matchesRole = roleFilter === "all" || action.required_role === roleFilter;
      return matchesSearch && matchesRisk && matchesApproval && matchesRole;
    });
  }, [actions, approvalFilter, riskFilter, roleFilter, search]);

  const selectedAction = actions.find((action) => action.action_id === selectedActionId) ?? null;

  return (
    <div className="screen-stack">
      <section className="panel smart-action-hero">
        <div>
          <p className="eyebrow">Integrations</p>
          <h2>Smart Action catalog</h2>
          <p className="screen-note">Discover the read-only action manifests available on this appliance. This catalog does not invoke actions or create runs.</p>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadActions()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </section>

      {error ? (
        <div className="notice danger" role="alert">
          <span>{error}</span>
          <button className="secondary-button" type="button" onClick={() => void loadActions()} disabled={loading}>Try again</button>
        </div>
      ) : null}

      {loading ? (
        <section className="panel" aria-busy="true">
          <p className="screen-note">Loading Smart Action catalog…</p>
        </section>
      ) : (
        <>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Available actions</h2>
                <span>{filteredActions.length} of {actions.length} action{actions.length === 1 ? "" : "s"}</span>
              </div>
              <span>Viewer access</span>
            </div>

            <div className="smart-action-filters">
              <label>
                Search actions
                <span className="search-box">
                  <Search size={17} aria-hidden="true" />
                  <input
                    aria-label="Search Smart Actions"
                    type="search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search by ID, title, or description"
                  />
                </span>
              </label>
              <label>
                Risk
                <select aria-label="Filter by risk" value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}>
                  <option value="all">All risk levels</option>
                  {riskOptions.map((risk) => <option key={risk} value={risk}>{risk}</option>)}
                </select>
              </label>
              <label>
                Approval
                <select aria-label="Filter by approval" value={approvalFilter} onChange={(event) => setApprovalFilter(event.target.value as ApprovalFilter)}>
                  <option value="all">Any approval setting</option>
                  <option value="required">Approval required</option>
                  <option value="not-required">No approval required</option>
                </select>
              </label>
              <label>
                Required role
                <select aria-label="Filter by role" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                  <option value="all">All roles</option>
                  {roleOptions.map((role) => <option key={role} value={role}>{role}</option>)}
                </select>
              </label>
            </div>

            {actions.length === 0 ? (
              <div className="empty-state">
                <h3>No Smart Actions are available.</h3>
                <p>The appliance did not publish any action manifests.</p>
              </div>
            ) : filteredActions.length === 0 ? (
              <div className="empty-state">
                <h3>No Smart Actions match these filters.</h3>
                <p>Try a different search or clear one of the filters.</p>
              </div>
            ) : (
              <div className="smart-action-table-wrap">
                <table className="smart-action-table">
                  <thead>
                    <tr>
                      <th scope="col">Action</th>
                      <th scope="col">Description</th>
                      <th scope="col">Risk</th>
                      <th scope="col">Approval</th>
                      <th scope="col">Role</th>
                      <th scope="col">Required connectors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredActions.map((action) => (
                      <tr key={action.action_id}>
                        <td>
                          <button className="smart-action-row-trigger" type="button" aria-label={action.title} onClick={() => setSelectedActionId(action.action_id)}>
                            <strong>{action.title}</strong>
                            <code>{action.action_id}</code>
                          </button>
                        </td>
                        <td>{action.description}</td>
                        <td><StatusChip status={action.risk_level} hint="Manifest risk level" /></td>
                        <td><StatusChip status={action.requires_approval ? "pending_approval" : "not_required"} hint={action.requires_approval ? "Approval is required before execution." : "The manifest does not require approval."} /></td>
                        <td>{action.required_role}</td>
                        <td className="smart-action-muted">Not declared by this manifest</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {selectedAction ? <SmartActionDetail action={selectedAction} onClose={() => setSelectedActionId(null)} /> : null}
        </>
      )}
    </div>
  );
}

function SmartActionDetail({ action, onClose }: { action: SmartActionManifest; onClose: () => void }) {
  return (
    <aside className="panel smart-action-detail" aria-labelledby="smart-action-detail-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Smart Action detail</p>
          <h2 id="smart-action-detail-heading">{action.title}</h2>
          <code>{action.action_id}</code>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close Smart Action details">
          <X size={17} aria-hidden="true" />
          Close
        </button>
      </div>
      <p>{action.description}</p>
      <dl className="smart-action-detail-grid">
        <div><dt>Kind</dt><dd>{action.kind}</dd></div>
        <div><dt>Risk</dt><dd><StatusChip status={action.risk_level} /></dd></div>
        <div><dt>Approval required</dt><dd>{action.requires_approval ? "Yes" : "No"}</dd></div>
        <div><dt>Required role</dt><dd>{action.required_role}</dd></div>
        <div><dt>Access mode</dt><dd>{action.access_mode}</dd></div>
        <div><dt>Estimated minutes saved</dt><dd>{action.estimated_minutes_saved}</dd></div>
        <div><dt>Approval expiry seconds</dt><dd>{action.approval_expiry_seconds}</dd></div>
        <div><dt>Required connectors</dt><dd>Not declared by this manifest</dd></div>
      </dl>
      <div className="smart-action-schema-grid">
        <section>
          <h3>Input schema</h3>
          <pre className="smart-action-code"><code>{JSON.stringify(action.input_schema, null, 2)}</code></pre>
        </section>
        <section>
          <h3>Output schema</h3>
          <pre className="smart-action-code"><code>{JSON.stringify(action.output_schema, null, 2)}</code></pre>
        </section>
      </div>
    </aside>
  );
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((left, right) => left.localeCompare(right));
}
