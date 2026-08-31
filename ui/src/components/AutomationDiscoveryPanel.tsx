import { useState } from "react";
import { apiFetch } from "../api/client";

type WorkflowMatch = {
  id: string;
  name?: string;
  approval_required?: boolean;
  risk_level?: string;
  available: boolean;
};

type Prerequisite = { family: string; status: string };

type Opportunity = {
  category_id: string;
  label: string;
  ticket_count: number;
  measured_labor_available: boolean;
  measured_labor_minutes: number;
  measured_labor_ticket_count: number;
  estimated_automation_minutes: number;
  estimate: boolean;
  readiness: string;
  workflow_matches: WorkflowMatch[];
  playbook_matches: WorkflowMatch[];
  prerequisites: Prerequisite[];
  source_ticket_ids: string[];
  source_ticket_ids_truncated: boolean;
  reason: string;
};

type DiscoveryResult = {
  client_id: string;
  window_days: number;
  ticket_count: number;
  opportunity_count: number;
  opportunities: Opportunity[];
  labor: {
    measured_minutes: number;
    measured: boolean;
    measured_ticket_count: number;
    estimate_minutes: number;
    estimate: boolean;
    derivation: string;
  };
  mapping_readiness: {
    verified_count: number;
    unverified_count: number;
    families: Record<string, { verified: number; unverified: number }>;
  };
  side_effects: boolean;
  automation_enabled: boolean;
  next_step: string;
};

export function AutomationDiscoveryPanel() {
  const [clientId, setClientId] = useState("");
  const [days, setDays] = useState(60);
  const [minTickets, setMinTickets] = useState(3);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const runDiscovery = async () => {
    const normalizedClient = clientId.trim();
    if (!normalizedClient) {
      setMessage("Select a client before analyzing historical tickets.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const query = new URLSearchParams({
        client_id: normalizedClient,
        days: String(days),
        min_tickets: String(minTickets)
      });
      const data = await apiFetch<DiscoveryResult>(`/packs/automation-discovery/historical?${query.toString()}`);
      setResult(data);
    } catch (error) {
      setResult(null);
      setMessage(error instanceof Error ? error.message : "Unable to analyze historical PSA tickets.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="automation-discovery-heading">
      <div className="panel-heading">
        <div>
          <h2 id="automation-discovery-heading">Historical automation discovery</h2>
          <p className="screen-note">
            Analyze prior PSA ticket evidence, identify repeated work, and map candidates to existing WAIT workflows.
            Discovery never enables or runs an automation.
          </p>
        </div>
        <span>{result ? `${result.opportunity_count} opportunities` : "read-only analysis"}</span>
      </div>

      <div className="analytics-filters">
        <label>
          Client ID
          <input value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder="Required client" />
        </label>
        <label>
          History window
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            <option value={30}>30 days</option>
            <option value={60}>60 days</option>
            <option value={90}>90 days</option>
            <option value={180}>180 days</option>
          </select>
        </label>
        <label>
          Minimum repeated tickets
          <input
            type="number"
            min={2}
            max={100}
            value={minTickets}
            onChange={(event) => setMinTickets(Number(event.target.value))}
          />
        </label>
        <div className="analytics-filter-actions">
          <button type="button" disabled={loading} onClick={() => void runDiscovery()}>
            {loading ? "Analyzing…" : "Analyze ticket history"}
          </button>
        </div>
      </div>

      {message ? <div className="notice" role="alert">{message}</div> : null}

      {result ? (
        <div className="screen-stack">
          <div className="analytics-metrics">
            <DiscoveryMetric label="Tickets analyzed" value={String(result.ticket_count)} detail={`${result.window_days}-day window`} />
            <DiscoveryMetric
              label="Measured PSA labor"
              value={result.labor.measured ? `${result.labor.measured_minutes} min` : "Unavailable"}
              detail={result.labor.measured ? `${result.labor.measured_ticket_count} tickets with time entries` : "No normalized PSA time entries; nothing inferred"}
            />
            <DiscoveryMetric
              label="Opportunity estimate"
              value={`${result.labor.estimate_minutes} min`}
              detail="Declared category estimate, not measured savings"
            />
            <DiscoveryMetric
              label="Verified mappings"
              value={String(result.mapping_readiness.verified_count)}
              detail={`${result.mapping_readiness.unverified_count} mappings still need review`}
            />
          </div>

          <p className="screen-note">{result.labor.derivation}</p>

          {result.opportunities.length === 0 ? (
            <p>No repeated ticket family reached the selected evidence threshold.</p>
          ) : (
            <div className="analytics-list">
              {result.opportunities.map((opportunity, index) => (
                <article className="analytics-row" key={opportunity.category_id}>
                  <div>
                    <strong>{String(index + 1).padStart(2, "0")} · {opportunity.label}</strong>
                    <span>{opportunity.ticket_count} historical tickets · {opportunity.readiness.replaceAll("_", " ")}</span>
                    <small>{opportunity.reason}</small>
                  </div>
                  <div>
                    <strong>{opportunity.measured_labor_available ? `${opportunity.measured_labor_minutes} min measured` : "Labor unavailable"}</strong>
                    <span>{opportunity.estimated_automation_minutes} min opportunity estimate</span>
                  </div>
                  <div className="analytics-statuses">
                    {opportunity.workflow_matches.length > 0 ? (
                      <span>Workflows: {opportunity.workflow_matches.map((item) => item.name ?? item.id).join(", ")}</span>
                    ) : null}
                    {opportunity.playbook_matches.length > 0 ? (
                      <span>Playbooks: {opportunity.playbook_matches.map((item) => item.name ?? item.id).join(", ")}</span>
                    ) : null}
                    {opportunity.prerequisites.length > 0 ? (
                      <span>Prerequisites: {opportunity.prerequisites.map((item) => `${item.family}=${item.status}`).join(" · ")}</span>
                    ) : null}
                    <span>
                      Evidence: {opportunity.source_ticket_ids.join(", ")}{opportunity.source_ticket_ids_truncated ? " …" : ""}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}

          <div className="notice" role="status">
            {result.next_step}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function DiscoveryMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="analytics-metric">
      <div><span>{label}</span></div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}
