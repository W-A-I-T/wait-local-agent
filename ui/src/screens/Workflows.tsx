import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { type WorkflowRun, type WorkflowTemplate } from "../api/types";

export function Workflows() {
  const { isAdmin, canWrite } = useDashboard();
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<WorkflowRun | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [clientId, setClientId] = useState("");
  const [message, setMessage] = useState("");

  const refreshRuns = useCallback(async () => {
    try {
      setRunsLoading(true);
      const [runRows, templateRows] = await Promise.all([
        apiFetch<WorkflowRun[]>('/workflow-runs'),
        apiFetch<WorkflowTemplate[]>('/workflows/templates')
      ]);
      setRuns(runRows);
      setTemplates(templateRows);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load workflow templates and runs.");
    } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  async function runTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!templateId || !ticketId) {
      setMessage("Choose a template and provide a ticket id.");
      return;
    }
    try {
      const payload = { template_id: templateId, ticket_id: ticketId, client_id: clientId || undefined };
      await apiFetch<WorkflowRun>(`/workflows/templates/${encodeURIComponent(templateId)}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      setMessage("Workflow run started.");
      await refreshRuns();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start workflow run.");
    }
  }

  async function openRun(runId: string | number) {
    try {
      const detail = await apiFetch<WorkflowRun>(`/workflow-runs/${runId}`);
      setSelectedRun(detail);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Workflow detail unavailable.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Workflows</h2>
          <span>{templates.length} templates</span>
        </div>
        <form className="draft-form" onSubmit={runTemplate}>
          <div className="grid">
            <label>
              Template
              <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
                <option value="">Choose template</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>{template.name}</option>
                ))}
              </select>
            </label>
            <label>
              Ticket id
              <input value={ticketId} onChange={(event) => setTicketId(event.target.value)} placeholder="HALO-1001" />
            </label>
            <label>
              Client id (optional)
              <input value={clientId} onChange={(event) => setClientId(event.target.value)} />
            </label>
          </div>
          <button type="submit" disabled={!canWrite || !templateId || !ticketId}>
            Start Workflow
          </button>
        </form>
        {message ? <div className="notice">{message}</div> : null}

        <div className="table-list">
          {templates.length === 0 ? <p>No templates available.</p> : null}
          {templates.map((template) => (
            <article className="table-row" key={template.id}>
              <div>
                <strong>{template.name}</strong>
                <span>{template.description || template.trigger}</span>
              </div>
              <span>{template.approval_required ? "requires approval" : "no approval"}</span>
              <em>{template.risk_level}</em>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Recent workflow runs</h2>
          <span>{runsLoading ? "loading" : runs.length}</span>
        </div>
        {runs.length === 0 ? <p>No runs yet.</p> : null}
        <div className="event-list">
          {runs.map((run) => (
            <article className="event-row" key={run.id}>
              <span>{run.template_id || run.id}</span>
              <em>{run.status}</em>
              <button type="button" onClick={() => void openRun(run.id)} className="icon-button">Open</button>
              <p>{run.message || `Ticket ${run.ticket_id || "n/a"}`}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Run detail</h2>
          <span>{selectedRun ? `Run ${selectedRun.id}` : "select one"}</span>
        </div>
        {selectedRun ? (
          <div className="approval-row">
            <div>
              <strong>Status</strong>
              <span>{selectedRun.status}</span>
            </div>
            <div>
              <strong>Template</strong>
              <span>{selectedRun.template_id || "n/a"}</span>
            </div>
            <div>
              <strong>Ticket</strong>
              <span>{selectedRun.ticket_id || "n/a"}</span>
            </div>
            <p>{selectedRun.message || "No detail yet."}</p>
          </div>
        ) : <p>Open a run to show live details.</p>}
        {!isAdmin ? <p className="screen-note">Run execution visibility is role-aware from your current credentials.</p> : null}
      </section>
    </div>
  );
}
