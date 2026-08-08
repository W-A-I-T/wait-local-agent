import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import type { AgentDefinition, ScheduledJob, ScheduledJobRequestBody, WorkflowTemplate } from "../api/types";

export function ScheduledJobs() {
  const { canWrite } = useDashboard();
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [scheduleKind, setScheduleKind] = useState<"workflow" | "agent">("workflow");
  const [templateId, setTemplateId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [entityId, setEntityId] = useState("HALO-1");
  const [cron, setCron] = useState("0 */6 * * *");
  const [timezone, setTimezone] = useState("UTC");
  const [paramsText, setParamsText] = useState("{\n  \"ticket_id\": \"HALO-1\"\n}");
  const [selectedJob, setSelectedJob] = useState<ScheduledJob | null>(null);
  const [message, setMessage] = useState("");
  const selectedAgent = agents.find((agent) => agent.id === agentId);

  const refresh = useCallback(async () => {
    try {
      const [jobsResponse, templatesResponse, agentsResponse] = await Promise.all([
        apiFetch<ScheduledJob[]>("/scheduled-jobs"),
        apiFetch<WorkflowTemplate[]>("/workflows/templates"),
        apiFetch<AgentDefinition[]>("/agents")
      ]);
      setJobs(jobsResponse);
      setTemplates(templatesResponse);
      setAgents(agentsResponse);
      if (!templateId && templatesResponse[0]) {
        setTemplateId(templatesResponse[0].id);
      }
      const firstScheduledAgent = agentsResponse.find((agent) => agent.trigger === "scheduled" && agent.enabled);
      if (!agentId && firstScheduledAgent) {
        setAgentId(firstScheduledAgent.id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load scheduled jobs.");
    }
  }, [agentId, templateId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if ((!templateId && scheduleKind === "workflow") || (!agentId && scheduleKind === "agent") || !cron) {
      setMessage("A target and cron expression are required.");
      return;
    }
    if (scheduleKind === "agent" && !entityId.trim()) {
      setMessage("An entity ID is required for agent schedules.");
      return;
    }

    let params: Record<string, unknown> = {};
    try {
      params = JSON.parse(paramsText);
    } catch {
      setMessage("Params must be valid JSON.");
      return;
    }

    try {
      const body: ScheduledJobRequestBody = scheduleKind === "agent"
        ? { agent_id: agentId, entity_id: entityId.trim(), cron, timezone: timezone.trim(), params }
        : { template_id: templateId, cron, timezone: timezone.trim(), params };
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
              Schedule type
              <select value={scheduleKind} onChange={(event) => setScheduleKind(event.target.value as "workflow" | "agent")}>
                <option value="workflow">Workflow template</option>
                <option value="agent">Agent definition</option>
              </select>
            </label>
            {scheduleKind === "workflow" ? (
              <label>
                Template
                <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
                  <option value="">Choose template</option>
                  {templates.map((template) => (
                    <option key={template.id} value={template.id}>{template.name}</option>
                  ))}
                </select>
              </label>
            ) : (
              <>
                <label>
                  Agent
                  <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
                    <option value="">Choose scheduled agent</option>
                    {agents.filter((agent) => agent.trigger === "scheduled" && agent.enabled).map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Entity ID
                  <input value={entityId} onChange={(event) => setEntityId(event.target.value)} />
                </label>
                {selectedAgent ? (
                  <div className="notice">
                    {selectedAgent.execution_window_start && selectedAgent.execution_window_end
                      ? `Agent window: ${selectedAgent.execution_window_start}–${selectedAgent.execution_window_end} (${selectedAgent.execution_window_timezone ?? "UTC"}).`
                      : "Agent window: runs any time."}
                  </div>
                ) : null}
              </>
            )}
            <label>
              Cron
              <input value={cron} onChange={(event) => setCron(event.target.value)} />
            </label>
            <label>
              Schedule timezone (IANA)
              <input value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="America/Vancouver" />
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
                <strong>{job.job_kind === "agent" ? `Agent ${job.agent_id}` : job.template_id}</strong>
                <span>{job.cron} ({job.timezone})</span>
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
              <span>{selectedJob.job_kind === "agent" ? `Agent ${selectedJob.agent_id}` : selectedJob.template_id}</span>
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
