import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import {
  type CollectorConfigPayload,
  type CollectorModule,
  type CollectorPreviewResult,
  type CollectorRun,
  type CollectorRunDetail,
  type CollectorValidationResult
} from "../api/types";

type JsonText = string | number | boolean | null;

type CollectorConfigText = {
  [key: string]: JsonText | { [nested: string]: JsonText };
};

export function Collectors() {
  const { canWrite } = useDashboard();
  const [modules, setModules] = useState<CollectorModule[]>([]);
  const [selectedModule, setSelectedModule] = useState("");
  const [configText, setConfigText] = useState(`{
  "source_name": "demo"
}`);
  const [clientId, setClientId] = useState("");
  const [validation, setValidation] = useState<CollectorValidationResult | null>(null);
  const [preview, setPreview] = useState<CollectorPreviewResult | null>(null);
  const [runs, setRuns] = useState<CollectorRun[]>([]);
  const [runDetail, setRunDetail] = useState<CollectorRunDetail | null>(null);
  const [message, setMessage] = useState("");
  const [exportText, setExportText] = useState("");

  const config = useMemo(() => {
    try {
      return JSON.parse(configText) as CollectorConfigText;
    } catch {
      return {};
    }
  }, [configText]);

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
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load collector screens.");
    }
  }, [selectedModule]);

  useEffect(() => {
    void load();
  }, [load]);

  function parsedPayload(): CollectorConfigPayload {
    return {
      config: config as CollectorConfigPayload["config"],
      client_id: clientId || undefined
    };
  }

  async function validateModule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedModule) {
      setMessage("Choose a collector module first.");
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
      setMessage(`Validation ${result.passed ? "passed" : "failed"}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Validation failed.");
    }
  }

  async function previewModule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedModule) {
      setMessage("Choose a collector module first.");
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
      setMessage("Preview ready.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Preview failed.");
    }
  }

  async function runModule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedModule) {
      setMessage("Choose a collector module first.");
      return;
    }
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
      setMessage(`Run queued ${result.id}`);
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
          <span>{modules.length} modules</span>
        </div>
        <form className="draft-form" onSubmit={validateModule}>
          <label>
            Module
            <select value={selectedModule} onChange={(event) => setSelectedModule(event.target.value)}>
              <option value="">Select module</option>
              {modules.map((module) => (
                <option key={module.id} value={module.id}>{module.name}</option>
              ))}
            </select>
          </label>
          <label>
            Client id
            <input value={clientId} onChange={(event) => setClientId(event.target.value)} />
          </label>
          <label>
            Config JSON
            <textarea rows={8} value={configText} onChange={(event) => setConfigText(event.target.value)} />
          </label>
          <div className="row-actions">
            <button type="submit">Validate</button>
            <button type="button" className="icon-button" onClick={() => void previewModule({} as FormEvent<HTMLFormElement>)}>
              Preview
            </button>
            <button
              type="button"
              className="icon-button"
              disabled={!canWrite}
              onClick={() => void runModule({} as FormEvent<HTMLFormElement>)}
            >
              Run now
            </button>
          </div>
        </form>

        {validation ? (
          <div className="notice">
            {validation.passed ? "Validation passed: " : "Validation failed: "}
            {validation.message}
            {validation.errors.length ? <p>{validation.errors.join("; ")}</p> : null}
          </div>
        ) : null}

        {preview ? (
          <div className="audit-list">
            <p>Preview for {preview.module_id}: {preview.scopes.join(", ")}</p>
            <p>Estimated assets: {preview.estimated_assets}, observations: {preview.estimated_observations}</p>
          </div>
        ) : null}

        {message ? <div className="notice">{message}</div> : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Collector runs</h2>
          <span>{runs.length}</span>
        </div>
        {runs.length === 0 ? <p>No runs yet.</p> : null}
        <div className="table-list">
          {runs.map((run) => (
            <article className="table-row" key={run.id}>
              <div>
                <strong>{run.module_id}</strong>
                <span>{run.status}</span>
              </div>
              <span>{run.mode}</span>
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
              <span>{runDetail.status}</span>
              <em>{runDetail.mode}</em>
              <span>{runDetail.module_id}</span>
              <p>{runDetail.updated_at}</p>
            </div>
            <pre className="code-panel">{JSON.stringify(runDetail, null, 2)}</pre>
          </>
        ) : <p>Open a collector run for details.</p>}
        {exportText ? <pre className="code-panel">{exportText}</pre> : null}
      </section>
    </div>
  );
}
