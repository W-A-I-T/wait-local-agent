import { useEffect, useState, type FormEvent } from "react";
import { ApiRequestError, apiFetch } from "../api/client";
import type {
  AutomationDiscoveryCategory,
  AutomationDiscoveryStatus,
  AutomationMappingReadiness,
  AutomationTimeEntryImportResponse
} from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { ScopeBadge } from "./ScopeBadge";
import { RoleGate } from "./RoleGate";

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
  const { isAdmin, role, roleResolved, clients = [], selectedClientId = "", isMspAdmin = false } = useDashboard();
  const [days, setDays] = useState(60);
  const [minTickets, setMinTickets] = useState(3);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [discoveryStatus, setDiscoveryStatus] = useState<AutomationDiscoveryStatus | null>(null);
  const [categories, setCategories] = useState<AutomationDiscoveryCategory[]>([]);
  const [readiness, setReadiness] = useState<AutomationMappingReadiness | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessMessage, setReadinessMessage] = useState("");
  const [importJson, setImportJson] = useState("");
  const [importLoading, setImportLoading] = useState(false);
  const [importMessage, setImportMessage] = useState("");
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState<AutomationTimeEntryImportResponse | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.allSettled([
      apiFetch<AutomationDiscoveryStatus>("/packs/automation-discovery/status"),
      apiFetch<AutomationDiscoveryCategory[]>("/packs/automation-discovery/categories")
    ]).then(([statusResult, categoriesResult]) => {
      if (!active) return;
      if (statusResult.status === "fulfilled") setDiscoveryStatus(statusResult.value);
      if (categoriesResult.status === "fulfilled") setCategories(categoriesResult.value);
      if (statusResult.status === "rejected" || categoriesResult.status === "rejected") {
        setMessage("Some automation discovery details could not be loaded. Try again later.");
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const normalizedClient = selectedClientId.trim();
    if (!normalizedClient || !clients.some((client) => client.client_id === normalizedClient)) {
      setReadiness(null);
      setReadinessMessage("");
      return;
    }
    let active = true;
    setReadinessLoading(true);
    setReadinessMessage("");
    void apiFetch<AutomationMappingReadiness>(
      `/packs/automation-discovery/mapping-readiness?client_id=${encodeURIComponent(normalizedClient)}`
    )
      .then((data) => {
        if (active) setReadiness(data);
      })
      .catch((error: unknown) => {
        if (active) {
          setReadiness(null);
          setReadinessMessage(errorMessage(error, "Unable to load mapping readiness."));
        }
      })
      .finally(() => {
        if (active) setReadinessLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedClientId, clients]);

  const runDiscovery = () => {
    const normalizedClient = selectedClientId.trim();
    if (!normalizedClient || !clients.some((client) => client.client_id === normalizedClient)) {
      setMessage("Select a client before analyzing historical tickets.");
      return;
    }
    setLoading(true);
    setMessage("");
    const query = new URLSearchParams({
      client_id: normalizedClient,
      days: String(days),
      min_tickets: String(minTickets)
    });
    void apiFetch<DiscoveryResult>(`/packs/automation-discovery/historical?${query.toString()}`)
      .then((data) => {
        setResult(data);
      })
      .catch((error: unknown) => {
        setResult(null);
        setMessage(error instanceof Error ? error.message : "Unable to analyze historical PSA tickets.");
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const importTimeEntries = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedClient = selectedClientId.trim();
    if (!normalizedClient || !clients.some((client) => client.client_id === normalizedClient)) {
      setImportError("Select a client before importing time entries.");
      return;
    }
    let entries: Array<Record<string, unknown>>;
    try {
      entries = parseTimeEntries(importJson);
    } catch (error: unknown) {
      setImportError(error instanceof Error ? error.message : "Enter a valid time-entry JSON array.");
      return;
    }
    setImportLoading(true);
    setImportError("");
    setImportMessage("");
    setImportResult(null);
    try {
      const imported = await apiFetch<AutomationTimeEntryImportResponse>("/packs/automation-discovery/time-entries/import", {
        method: "POST",
        body: JSON.stringify({ client_id: normalizedClient, entries })
      });
      setImportResult(imported);
      setImportMessage(`Time entries imported for ${imported.client_id}.`);
    } catch (error: unknown) {
      setImportError(errorMessage(error, "Unable to import time entries."));
    } finally {
      setImportLoading(false);
    }
  };

  const accessRole = role ?? (isAdmin ? "admin" : "viewer");

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
        <span><ScopeBadge /> · {result ? `${result.opportunity_count} opportunities` : "read-only analysis"}</span>
      </div>

      {discoveryStatus ? (
        <div className="connection-state" role="status">
          <span>Discovery status: {discoveryStatus.status}</span>
          <span>External writes: {discoveryStatus.external_writes ? "enabled" : "not used"}</span>
          <span>{categories.length} discovery categories available</span>
        </div>
      ) : null}
      {categories.length > 0 ? (
        <details>
          <summary>Available discovery categories</summary>
          <ul>
            {categories.map((category) => <li key={category.category_id}>{category.label} · {category.default_minutes_estimate} minute estimate</li>)}
          </ul>
        </details>
      ) : null}

      <div className="analytics-filters">
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
          <button type="button" disabled={loading || !selectedClientId} onClick={runDiscovery}>
            {loading ? "Analyzing…" : "Analyze ticket history"}
          </button>
        </div>
      </div>

      {!selectedClientId && !isMspAdmin ? <div className="notice" role="status">Choose a client in the top bar to continue.</div> : null}
      {message ? <div className="notice" role="alert">{message}</div> : null}
      {readinessLoading ? <p className="screen-note" aria-busy="true">Loading mapping readiness…</p> : null}
      {readinessMessage ? <div className="notice danger" role="alert">{readinessMessage}</div> : null}

      {readiness ? (
        <section aria-labelledby="automation-readiness-heading">
          <div className="panel-heading">
            <h3 id="automation-readiness-heading">Mapping readiness</h3>
            <span>{readiness.verified_count} verified · {readiness.unverified_count} needs review</span>
          </div>
          {Object.keys(readiness.families ?? {}).length === 0 ? (
            <p className="screen-note">No connector mappings are recorded for this client.</p>
          ) : (
            <div className="table-list settings-list">
              {Object.entries(readiness.families ?? {}).map(([family, counts]) => (
                <div key={family}>
                  <dt>{family}</dt>
                  <dd>{counts.verified} verified · {counts.unverified} unverified</dd>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}

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

      <RoleGate
        role={accessRole}
        resolved={roleResolved}
        allowed={["admin"]}
        fallback={<p className="screen-note">Administrator access is required to import time-entry evidence.</p>}
      >
        <section className="panel" aria-labelledby="time-entry-import-heading">
          <div className="panel-heading">
            <div>
              <h3 id="time-entry-import-heading">Import time-entry evidence</h3>
              <p className="screen-note">Provide a JSON array with normalized PSA time entries. Credentials and unknown fields are rejected and never sent or displayed.</p>
            </div>
            <span>local evidence only</span>
          </div>
          <form onSubmit={importTimeEntries}>
            <label htmlFor="time-entry-file">Load JSON file</label>
            <input
              id="time-entry-file"
              type="file"
              accept=".json,application/json"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                void file.text().then(setImportJson).catch(() => setImportError("The selected JSON file could not be read."));
                event.target.value = "";
              }}
            />
            <label htmlFor="time-entry-json">Time-entry JSON</label>
            <textarea
              id="time-entry-json"
              rows={7}
              value={importJson}
              onChange={(event) => setImportJson(event.target.value)}
              placeholder='[{"ticket_id":"T-100","connector_instance_id":"psa-acme","external_time_entry_id":"entry-1","minutes":30,"work_type":"remote support","occurred_at":"2026-08-30T18:00:00Z","source_system":"psa"}]'
              spellCheck={false}
            />
            <button type="submit" disabled={importLoading || !selectedClientId}>
              {importLoading ? "Importing…" : "Import time entries"}
            </button>
          </form>
          {importError ? <div className="notice danger" role="alert">{importError}</div> : null}
          {importMessage ? <div className="notice" role="status">{importMessage}</div> : null}
          {importResult ? (
            <div className="connection-state" role="status" aria-label="Time-entry import result">
              <span>Inserted: {importResult.inserted}</span>
              <span>Duplicates: {importResult.duplicate}</span>
              <span>Rejected: {importResult.rejected}</span>
              <span>External writes: {importResult.external_writes ? "enabled" : "not used"}</span>
            </div>
          ) : null}
        </section>
      </RoleGate>
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

const TIME_ENTRY_FIELDS = [
  "ticket_id",
  "connector_instance_id",
  "external_time_entry_id",
  "minutes",
  "work_type",
  "occurred_at",
  "source_system"
] as const;
const CREDENTIAL_TEXT = /\b(api[_-]?key|access[_-]?token|client[_-]?secret|password|authorization)\s*[:=]/i;

function parseTimeEntries(value: string): Array<Record<string, unknown>> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("Enter a valid time-entry JSON array.");
  }
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error("Enter at least one time entry in a JSON array.");
  }
  return parsed.map((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error("Each time entry must be a JSON object.");
    }
    const record = entry as Record<string, unknown>;
    if (Object.keys(record).some((key) => !TIME_ENTRY_FIELDS.includes(key as typeof TIME_ENTRY_FIELDS[number]))) {
      throw new Error("Time entries may contain only the documented evidence fields; credentials are not accepted.");
    }
    if (Object.values(record).some((item) => typeof item === "string" && CREDENTIAL_TEXT.test(item))) {
      throw new Error("Credential-like values are not accepted in time-entry evidence.");
    }
    return Object.fromEntries(TIME_ENTRY_FIELDS.filter((field) => field in record).map((field) => [field, record[field]]));
  });
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError || error instanceof Error ? error.message : fallback;
}
