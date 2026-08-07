import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import {
  type CollectorConfigPayload,
  type CollectorModule,
  type CollectorPreviewResult,
  type CollectorRun,
  type CollectorRunDetail,
  type CollectorRunResult,
  type CollectorValidationResult
} from "../api/types";
import { SchemaForm, defaultsForFields, validateRequiredFields, type SchemaFormValue } from "../components/SchemaForm";
import { ScopeChip, StatusChip } from "../components/StatusChip";

export function Collectors() {
  const { canWrite } = useDashboard();
  const [modules, setModules] = useState<CollectorModule[]>([]);
  const [selectedModule, setSelectedModule] = useState("");
  const [config, setConfig] = useState<SchemaFormValue>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [clientId, setClientId] = useState("");
  const [validation, setValidation] = useState<CollectorValidationResult | null>(null);
  const [preview, setPreview] = useState<CollectorPreviewResult | null>(null);
  const [runs, setRuns] = useState<CollectorRun[]>([]);
  const [runDetail, setRunDetail] = useState<CollectorRunDetail | null>(null);
  const [confirmingRun, setConfirmingRun] = useState(false);
  const [message, setMessage] = useState("");
  const [exportText, setExportText] = useState("");

  const activeModule = useMemo(
    () => modules.find((module) => module.id === selectedModule),
    [modules, selectedModule]
  );

  const runResult = useMemo(() => parseRunResult(runDetail), [runDetail]);

  const load = useCallback(async () => {
    try {
      const [moduleRows, runRows] = await Promise.all([
        apiFetch<CollectorModule[]>("/collectors/modules"),
        apiFetch<CollectorRun[]>("/collectors/runs")
      ]);
      setModules(moduleRows);
      setRuns(runRows);
      if (!selectedModule && moduleRows[0]) {
        setSelectedModule(moduleRows[0].id);
        setConfig(defaultsForFields(moduleRows[0].config_schema ?? []));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load collector screens.");
    }
  }, [selectedModule]);

  useEffect(() => {
    void load();
  }, [load]);

  function selectModule(moduleId: string) {
    setSelectedModule(moduleId);
    const next = modules.find((module) => module.id === moduleId);
    setConfig(defaultsForFields(next?.config_schema ?? []));
    setFieldErrors({});
    setValidation(null);
    setPreview(null);
    setConfirmingRun(false);
  }

  function parsedPayload(): CollectorConfigPayload {
    return {
      config,
      client_id: clientId || undefined
    };
  }

  function checkRequiredFields(): boolean {
    const errors = validateRequiredFields(activeModule?.config_schema ?? [], config);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setMessage("Some required settings are missing — fix the highlighted fields and try again.");
      return false;
    }
    return true;
  }

  async function validateModule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedModule) {
      setMessage("Choose a collector first.");
      return;
    }
    if (!checkRequiredFields()) {
      return;
    }
    try {
      const result = await apiFetch<CollectorValidationResult>(
        `/collectors/modules/${encodeURIComponent(selectedModule)}/validate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(parsedPayload())
        }
      );
      setValidation(result);
      setMessage(result.passed ? "Settings look good." : "The settings need attention.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Validation failed.");
    }
  }

  async function previewModule() {
    if (!selectedModule) {
      setMessage("Choose a collector first.");
      return;
    }
    if (!checkRequiredFields()) {
      return;
    }
    try {
      const result = await apiFetch<CollectorPreviewResult>(
        `/collectors/modules/${encodeURIComponent(selectedModule)}/preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(parsedPayload())
        }
      );
      setPreview(result);
      setMessage("Preview ready — nothing has been collected yet.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Preview failed.");
    }
  }

  function requestRun() {
    if (!selectedModule) {
      setMessage("Choose a collector first.");
      return;
    }
    if (!checkRequiredFields()) {
      return;
    }
    setConfirmingRun(true);
  }

  async function confirmRun() {
    setConfirmingRun(false);
    try {
      const result = await apiFetch<CollectorRun>(
        `/collectors/modules/${encodeURIComponent(selectedModule)}/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...parsedPayload(), confirm: true })
        }
      );
      await load();
      setMessage("Run started.");
      await openRun(result.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Run failed.");
    }
  }

  async function openRun(runId: number) {
    try {
      const detail = await apiFetch<CollectorRunDetail>(`/collectors/runs/${runId}`);
      setRunDetail(detail);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to open collector run detail.");
    }
  }

  async function exportRun(runId: number) {
    try {
      const response = await apiFetch<unknown>(`/collectors/runs/${runId}/export`);
      const text = typeof response === "string" ? response : JSON.stringify(response, null, 2);
      setExportText(text);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Export failed.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Collectors</h2>
          <span>{modules.length} collectors</span>
        </div>
        <p className="screen-note">
          Collectors gather read-only information about this appliance. Pick one, check its settings,
          preview what it will find, then run it.
        </p>
        <form className="draft-form" noValidate onSubmit={validateModule}>
          <label>
            Collector
            <select value={selectedModule} onChange={(event) => selectModule(event.target.value)}>
              <option value="">Choose a collector</option>
              {modules.map((module) => (
                <option key={module.id} value={module.id}>{module.name}</option>
              ))}
            </select>
          </label>
          {activeModule ? <p className="screen-note">{activeModule.description}</p> : null}
          <label>
            Client id
            <input value={clientId} onChange={(event) => setClientId(event.target.value)} />
          </label>
          {activeModule ? (
            <SchemaForm
              fields={activeModule.config_schema ?? []}
              value={config}
              onChange={setConfig}
              errors={fieldErrors}
              idPrefix={`collector-${activeModule.id}`}
            />
          ) : null}
          <div className="row-actions">
            <button type="submit">Check settings</button>
            <button type="button" className="icon-button" onClick={() => void previewModule()}>
              Preview
            </button>
            <button type="button" className="icon-button" disabled={!canWrite} onClick={requestRun}>
              Run now
            </button>
          </div>
        </form>

        {confirmingRun && activeModule ? (
          <div className="notice confirm-panel" role="alertdialog" aria-label="Confirm collector run">
            <p>
              Run {activeModule.name} now? It will collect read-only data with the settings above and
              store the results on this appliance.
            </p>
            <div className="row-actions">
              <button type="button" onClick={() => void confirmRun()}>
                Yes, run it
              </button>
              <button type="button" className="icon-button" onClick={() => setConfirmingRun(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        {validation ? (
          <div className={`notice${validation.passed ? "" : " danger"}`}>
            {validation.passed ? "Settings look good: " : "The settings need attention: "}
            <span>{humanizeValidationText(validation.message)}</span>
            {validation.errors.length ? (
              <ul>
                {validation.errors.map((error) => <li key={error}>{humanizeValidationText(error)}</li>)}
              </ul>
            ) : null}
            <TechnicalDetails values={[validation.message, ...validation.errors]} />
          </div>
        ) : null}

        {preview ? (
          <div className="audit-list">
            <p>
              Preview for {activeModule?.name ?? preview.module_id}. Covers: {preview.scopes.map(humanizeScope).join(", ")}
            </p>
            <TechnicalDetails values={preview.scopes} label="Technical scope details" />
            <p>
              Expects about {preview.estimated_assets} items and {preview.estimated_observations} observations.
            </p>
          </div>
        ) : null}

        {message ? <div className="notice">{message}</div> : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Collector runs</h2>
          <span>{runs.length}</span>
        </div>
        {runs.length === 0 ? (
          <p className="screen-note">
            No runs yet. Choose a collector above, check its settings, and preview what it will gather
            before running it for real.
          </p>
        ) : null}
        <div className="table-list">
          {runs.map((run) => (
            <article className="table-row" key={run.id}>
              <div>
                <strong>{modules.find((module) => module.id === run.module_id)?.name ?? run.module_id}</strong>
                <StatusChip status={run.status} />
                {run.result_status ? <StatusChip status={run.result_status} /> : null}
              </div>
              <button type="button" className="icon-button" onClick={() => void openRun(run.id)}>
                Open
              </button>
              <button type="button" className="icon-button" onClick={() => void exportRun(run.id)}>
                Export
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Run detail / export</h2>
          <span>{runDetail ? `Run ${runDetail.id}` : "no run selected"}</span>
        </div>
        {runDetail ? (
          <>
            <div className="event-row">
              <StatusChip status={runDetail.status} />
              {runDetail.result_status ? <StatusChip status={runDetail.result_status} /> : null}
              <ScopeChip scope={runResult?.collection_scope} />
              <span>{modules.find((module) => module.id === runDetail.module_id)?.name ?? runDetail.module_id}</span>
              <p>{runDetail.updated_at}</p>
            </div>
            {runResult?.source_outcomes?.length ? (
              <div className="table-list">
                {runResult.source_outcomes.map((outcome) => (
                  <article className="table-row" key={outcome.source_id}>
                    <div>
                      <strong>{humanizeSourceId(outcome.source_id)}</strong>
                      <TechnicalDetails values={[`Source ID: ${outcome.source_id}`]} />
                      <StatusChip
                        status={outcome.status}
                        hint={outcome.remediation_hint ?? undefined}
                      />
                    </div>
                    <span>{outcome.record_count ?? 0} records</span>
                  </article>
                ))}
              </div>
            ) : null}
            <pre className="code-panel">{JSON.stringify(safeRunDetailForDisplay(runDetail), null, 2)}</pre>
          </>
        ) : (
          <p className="screen-note">Open a collector run to see what each source returned.</p>
        )}
        {exportText ? <pre className="code-panel">{exportText}</pre> : null}
      </section>
    </div>
  );
}

const SCOPE_LABELS: Record<string, string> = {
  local_host: "This computer",
  processes: "Running programs",
  network_sockets: "Network connections",
  network_interfaces: "Network interfaces",
  firewall_rules: "Firewall rules",
  databases: "Local databases",
  wifi_interfaces: "Wireless interfaces",
  routing_table: "Network routes",
  endpoint_agents: "Endpoint management tools",
  web_services: "Web services"
};

const SOURCE_PREFIX_LABELS: Record<string, string> = {
  process: "Running program",
  socket: "Network socket",
  interface: "Network interface",
  firewall: "Firewall configuration",
  database: "Database configuration",
  wifi: "Wireless network source",
  route: "Network route",
  agent: "Endpoint management tool",
  web: "Web service"
};

const SOURCE_ID_LABELS: Record<string, string> = {
  "wifi:proc-net-wireless": "Wireless device list",
  "wifi:sys-class-net": "Wireless interface details"
};

const VALIDATION_MESSAGE_LABELS: Record<string, string> = {
  "collector config must be a mapping": "The collector settings need attention.",
  "collector configuration is invalid": "The collector settings are not valid."
};

function humanizeScope(scope: string): string {
  return SCOPE_LABELS[scope] ?? humanizeTechnicalValue(scope);
}

function humanizeSourceId(sourceId: string): string {
  const exactLabel = SOURCE_ID_LABELS[sourceId];
  if (exactLabel) {
    return exactLabel;
  }
  const [prefix, ...parts] = sourceId.split(":");
  const prefixLabel = SOURCE_PREFIX_LABELS[prefix];
  if (!prefixLabel) {
    return humanizeTechnicalValue(sourceId);
  }
  if (parts.length === 0) {
    return prefixLabel;
  }
  return `${prefixLabel} (${parts.map(humanizeSourcePart).join(": ")})`;
}

function humanizeSourcePart(part: string): string {
  const knownProtocol = ["tcp", "udp", "ipv4", "ipv6"].includes(part.toLowerCase());
  return knownProtocol ? part.toUpperCase() : humanizeTechnicalValue(part);
}

function humanizeValidationText(text: string): string {
  const trimmed = text.trim();
  return VALIDATION_MESSAGE_LABELS[trimmed.toLowerCase()] ?? humanizeTechnicalValue(trimmed);
}

function humanizeTechnicalValue(value: string): string {
  const words = value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/:+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Not provided";
}

function TechnicalDetails({ values, label = "Technical details" }: { values: string[]; label?: string }) {
  const visibleValues = values.filter(Boolean);
  if (visibleValues.length === 0) {
    return null;
  }
  return (
    <details className="technical-details">
      <summary>{label}</summary>
      <ul>
        {visibleValues.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}
      </ul>
    </details>
  );
}

function safeRunDetailForDisplay(run: CollectorRunDetail): Record<string, unknown> {
  return {
    ...run,
    result_json: run.result_json ? "[hidden; source outcomes are shown above]" : undefined,
    config_snapshots: run.config_snapshots.length ? "[hidden from screen]" : [],
    config_diffs: run.config_diffs.length ? "[hidden from screen]" : []
  };
}

function parseRunResult(run: CollectorRunDetail | null): CollectorRunResult | null {
  if (!run?.result_json) {
    return null;
  }
  try {
    const parsed = JSON.parse(run.result_json) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return parsed as CollectorRunResult;
  } catch {
    return null;
  }
}
