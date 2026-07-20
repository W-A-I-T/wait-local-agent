import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import type { ScheduledJob, ScheduledJobRequestBody, WorkflowTemplate } from "../api/types";

export function ScheduledJobs() {
  const { canWrite } = useDashboard();
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [cron, setCron] = useState("0 */6 * * *");
  const [paramsText, setParamsText] = useState("{\n  \"ticket_id\": \"HALO-1\"\n}");
  const [selectedJob, setSelectedJob] = useState<ScheduledJob | null>(null);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [jobsResponse, templatesResponse] = await Promise.all([
        apiFetch<ScheduledJob[]>("/scheduled-jobs"),
        apiFetch<WorkflowTemplate[]>("/workflows/templates")
      ]);
      setJobs(jobsResponse);
      setTemplates(templatesResponse);
      if (!templateId && templatesResponse[0]) {
        setTemplateId(templatesResponse[0].id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load scheduled jobs.");
    }
  }, [templateId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!templateId || !cron) {
      setMessage("Template and cron expression are required.");
      return;
    }

    let params: Record<string, string | number | boolean> = {};
    try {
      params = JSON.parse(paramsText);
    } catch {
      setMessage("Params must be valid JSON.");
      return;
    }

    try {
      const body: ScheduledJobRequestBody = { template_id: templateId, cron, params };
      await apiFetch<ScheduledJob>("/scheduled-jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      setMessage("Scheduled job created.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create job.");
    }
  }

  async function controlJob(endpoint: "pause" | "resume" | "delete", jobId: number) {
    try {
      if (endpoint === "delete") {
        await apiFetch(`/scheduled-jobs/${jobId}`, {
          method: "DELETE"
        });
        if (selectedJob?.id === jobId) {
          setSelectedJob(null);
        }
      } else {
        const job = await apiFetch<ScheduledJob>(`/scheduled-jobs/${jobId}/${endpoint}`, {
          method: "POST"
        });
        setSelectedJob(job);
      }
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to update job.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Scheduled Jobs</h2>
          <span>{jobs.length} configured</span>
        </div>
        <form className="draft-form" onSubmit={createJob}>
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
              Cron
              <input value={cron} onChange={(event) => setCron(event.target.value)} />
            </label>
            <label>
              Params JSON
              <textarea rows={5} value={paramsText} onChange={(event) => setParamsText(event.target.value)} />
            </label>
          </div>
          <button type="submit" disabled={!canWrite}>Create schedule</button>
        </form>

        {message ? <div className="notice">{message}</div> : null}
        {jobs.length === 0 ? <p>No scheduled jobs yet.</p> : null}
        <div className="table-list">
          {jobs.map((job) => (
            <article className="table-row" key={job.id}>
              <div>
                <strong>{job.template_id}</strong>
                <span>{job.cron}</span>
              </div>
              <span>{job.paused ? "paused" : "running"}</span>
              <div>
                <button className="icon-button" type="button" onClick={() => setSelectedJob(job)}>Details</button>
                <button className="icon-button" type="button" disabled={!canWrite} onClick={() => void controlJob(job.paused ? "resume" : "pause", job.id)}>
                  {job.paused ? "Resume" : "Pause"}
                </button>
                <button className="icon-button" type="button" disabled={!canWrite} onClick={() => void controlJob("delete", job.id)}>
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Job detail</h2>
          <span>{selectedJob ? `Job ${selectedJob.id}` : "no job selected"}</span>
        </div>
        {selectedJob ? (
          <>
            <div className="event-row">
              <span>{selectedJob.template_id}</span>
              <em>{selectedJob.client_id || "global"}</em>
              <span>{selectedJob.next_run_at || "next run unknown"}</span>
            </div>
            <pre className="code-panel">{JSON.stringify(selectedJob, null, 2)}</pre>
          </>
        ) : <p>Select a job to inspect its runtime state.</p>}
      </section>
    </div>
  );
}
