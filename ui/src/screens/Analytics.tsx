import { Activity, CheckCircle2, Clock3, ShieldCheck, TicketCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { ClientIdSelect } from "../components/ClientIdSelect";
import { type AnalyticsSummary } from "../api/types";
import { AutomationDiscoveryPanel } from "../components/AutomationDiscoveryPanel";

const EMPTY_SUMMARY: AnalyticsSummary = {
  range: { from: null, to: null },
  client_id: null,
  executions_over_time: [],
  success_rate: { total: 0, succeeded: 0, rate: 0 },
  failures_by_status: [],
  activity_breakdown: [],
  approval_rate: {
    requested: 0,
    decided: 0,
    approved: 0,
    rejected: 0,
    pending: 0,
    rate: 0,
    derivation: "No approval requests in the selected range."
  },
  ticket_metrics: {
    touched: 0,
    resolved: 0,
    resolution_rate: 0,
    derivation: "No execution-referenced tickets in the selected range.",
    historical_resolution: {
      resolved_with_history: 0,
      with_duration: 0,
      average_minutes: null,
      derivation: "No local status transitions in the selected range."
    }
  },
  activity_by_workflow: [],
  estimated_minutes_saved: {
    minutes: 0,
    estimate: true,
    derivation: "No successful smart-action executions in the selected range."
  },
  model_usage: {
    runs_with_usage: 0,
    runs_with_cost: 0,
    input_tokens: 0,
    output_tokens: 0,
    estimated_cost_usd: 0,
    estimate: true,
    derivation: "No model usage recorded in the selected range."
  }
};

export function Analytics() {
  const { clients = [] } = useDashboard();
  const [summary, setSummary] = useState<AnalyticsSummary>(EMPTY_SUMMARY);
  const [startedFrom, setStartedFrom] = useState("");
  const [startedTo, setStartedTo] = useState("");
  const [clientId, setClientId] = useState("");
  const [filters, setFilters] = useState({ startedFrom: "", startedTo: "", clientId: "" });
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    const query = new URLSearchParams();
    if (filters.startedFrom) query.set("from", filters.startedFrom);
    if (filters.startedTo) query.set("to", filters.startedTo);
    if (filters.clientId) query.set("client_id", filters.clientId);
    const queryString = query.toString();
    void apiFetch<AnalyticsSummary>(`/analytics/summary${queryString ? `?${queryString}` : ""}`)
      .then((data) => {
        if (active) {
          setSummary(data);
          setMessage("");
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setMessage(error instanceof Error ? error.message : "Unable to load analytics.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [filters]);

  const successRate = formatPercent(summary.success_rate.rate);
  const approvalRate = formatPercent(summary.approval_rate.rate);
  const resolutionRate = formatPercent(summary.ticket_metrics.resolution_rate);
  const historicalResolution = summary.ticket_metrics.historical_resolution ?? {
    resolved_with_history: 0,
    with_duration: 0,
    average_minutes: null,
    derivation: "No local status transitions in the selected range."
  };
  const averageResolution = historicalResolution.average_minutes === null
    ? "No recorded duration"
    : `${historicalResolution.average_minutes} min average`;

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Analytics</h2>
            <p className="screen-note">Local execution activity for the current role and tenant scope.</p>
          </div>
          <span>{loading ? "loading" : "current range"}</span>
        </div>
        {message ? <div className="notice" role="alert">{message}</div> : null}
        <div className="analytics-metrics">
          <Metric icon={<Activity size={18} aria-hidden="true" />} label="Executions" value={String(summary.success_rate.total)} detail={`${successRate} successful`} />
          <Metric icon={<CheckCircle2 size={18} aria-hidden="true" />} label="Tickets resolved" value={String(summary.ticket_metrics.resolved)} detail={`${summary.ticket_metrics.touched} touched · ${resolutionRate}`} />
          <Metric icon={<TicketCheck size={18} aria-hidden="true" />} label="Recorded resolution" value={String(historicalResolution.resolved_with_history)} detail={`${averageResolution} · ${historicalResolution.with_duration} timed`} />
          <Metric icon={<ShieldCheck size={18} aria-hidden="true" />} label="Approval rate" value={approvalRate} detail={`${summary.approval_rate.requested} requested · ${summary.approval_rate.pending} pending`} />
          <Metric icon={<Clock3 size={18} aria-hidden="true" />} label="Estimated time saved" value={`${summary.estimated_minutes_saved.minutes} min`} detail="Estimate, not measured time" />
          <Metric icon={<Activity size={18} aria-hidden="true" />} label="Model cost estimate" value={formatUsd(summary.model_usage.estimated_cost_usd)} detail={`${summary.model_usage.runs_with_cost} priced runs · operator rates`} />
        </div>
        <p className="screen-note">Model cost is an estimate from provider-reported tokens and rates configured by the operator. Missing pricing or usage stays unpriced.</p>
      </section>

      <AutomationDiscoveryPanel />

      <section className="panel analytics-filter-panel">
        <div className="panel-heading">
          <div>
            <h2>Filter analytics</h2>
            <p className="screen-note">Filters are applied server-side within your permitted tenant scope.</p>
          </div>
          <span>{summary.client_id ? `Client: ${summary.client_id}` : "All permitted clients"}</span>
        </div>
        <div className="analytics-filters">
          <label>
            From date
            <input type="date" value={startedFrom} onChange={(event) => setStartedFrom(event.target.value)} />
          </label>
          <label>
            To date
            <input type="date" value={startedTo} onChange={(event) => setStartedTo(event.target.value)} />
          </label>
          <ClientIdSelect label="Client ID" value={clientId} onChange={setClientId} clients={clients} id="analytics-client-id" />
          <div className="analytics-filter-actions">
            <button type="button" onClick={() => setFilters({ startedFrom, startedTo, clientId })}>Apply filters</button>
            <button type="button" className="secondary-button" onClick={() => {
              setStartedFrom("");
              setStartedTo("");
              setClientId("");
              setFilters({ startedFrom: "", startedTo: "", clientId: "" });
            }}>Clear filters</button>
          </div>
        </div>
      </section>

      <div className="grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Workflow activity</h2>
            <span>{summary.activity_by_workflow.length} workflows</span>
          </div>
          {summary.activity_by_workflow.length === 0 ? <p>No workflow activity in this range.</p> : null}
          <div className="analytics-list">
            {summary.activity_by_workflow.map((item) => (
              <article className="analytics-row" key={`${item.run_kind}:${item.workflow_id}`}>
                <div>
                  <strong>{item.workflow_id}</strong>
                  <span>{item.run_kind}</span>
                </div>
                <div>
                  <strong>{item.total}</strong>
                  <span>{item.succeeded} successful</span>
                </div>
                <span className="analytics-statuses">
                  {item.status_counts.map((status) => `${status.status}: ${status.count}`).join(" · ")}
                </span>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>Outcome detail</h2>
            <span>{summary.failures_by_status.length} failure states</span>
          </div>
          <div className="analytics-detail">
            <div><TicketCheck size={17} aria-hidden="true" /><span>Approved</span><strong>{summary.approval_rate.approved}</strong></div>
            <div><ShieldCheck size={17} aria-hidden="true" /><span>Rejected</span><strong>{summary.approval_rate.rejected}</strong></div>
            {summary.failures_by_status.map((failure) => (
              <div key={failure.status}><Activity size={17} aria-hidden="true" /><span>{failure.status}</span><strong>{failure.count}</strong></div>
            ))}
          </div>
          <p className="screen-note">Resolution and time-saved figures use the derivations recorded by the appliance.</p>
        </section>
      </div>
    </div>
  );
}

function Metric({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return (
    <article className="analytics-metric">
      <div>{icon}<span>{label}</span></div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatUsd(value: number) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 8 }).format(value);
}
