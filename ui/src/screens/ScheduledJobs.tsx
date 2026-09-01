import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { ClientIdSelect } from "../components/ClientIdSelect";
import type { AgentDefinition, MspPlaybook, ScheduledJob, ScheduledJobRequestBody, WorkflowTemplate } from "../api/types";

export function ScheduledJobs() {
  const { canWrite, clients = [], selectedClientId, setSelectedClientId } = useDashboard();
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [playbooks, setPlaybooks] = useState<MspPlaybook[]>([]);
  const [loading, setLoading] = useState(true);
  const hasLoadedRef = useRef(false);
  const [scheduleKind, setScheduleKind] = useState<"workflow" | "playbook" | "agent" | "report">("workflow");
  const [templateId, setTemplateId] = useState("");
  const [reportType, setReportType] = useState<"qbr" | "automation_opportunity" | "recurring_service_review">("qbr");
  const [agentId, setAgentId] = useState("");
  const [playbookId, setPlaybookId] = useState("");
  const [entityId, setEntityId] = useState("HALO-1");
  const [cron, setCron] = useState("0 */6 * * *");
  const [timezone, setTimezone] = useState("UTC");
  const [paramsText, setParamsText] = useState("{\n  \"ticket_id\": \"HALO-1\"\n}");
  const [selectedJob, setSelectedJob] = useState<ScheduledJob | null>(null);
  const [message, setMessage] = useState("");
  const selectedAgent = agents.find((agent) => agent.id === agentId);

  const refresh = useCallback(async () => {
    if (!hasLoadedRef.current) setLoading(true);
    try {
      const [jobsResponse, templatesResponse, agentsResponse, playbooksResponse] = await Promise.all([
        apiFetch<ScheduledJob[]>("/scheduled-jobs"),
        apiFetch<WorkflowTemplate[]>("/workflows/templates"),
        apiFetch<AgentDefinition[]>("/agents"),
        apiFetch<MspPlaybook[]>("/msp/playbooks")
      ]);
      setJobs(jobsResponse);
      setTemplates(templatesResponse);
      setAgents(agentsResponse);
      setPlaybooks(playbooksResponse);
      if (!templateId && templatesResponse[0]) {
        setTemplateId(templatesResponse[0].id);
      }
      const firstScheduledAgent = agentsResponse.find((agent) => agent.trigger === "scheduled" && agent.enabled);
      if (!agentId && firstScheduledAgent) {
        setAgentId(firstScheduledAgent.id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load scheduled jobs.");
    } finally {
      hasLoadedRef.current = true;
      setLoading(false);
    }
  }, [agentId, templateId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if ((!templateId && scheduleKind === "workflow") || (!playbookId && scheduleKind === "playbook") || (!agentId && scheduleKind === "agent") || !cron) {
      setMessage("A target and cron expression are required.");
      return;
    }
    if (scheduleKind === "agent" && !entityId.trim()) {
      setMessage("An entity ID is required for agent schedules.");
      return;
    }
    const requiresClientScope = scheduleKind === "playbook" || scheduleKind === "report";
    if (requiresClientScope && !selectedClientId) {
      setMessage("Select a client from the top bar before creating this schedule.");
      return;
    }

    let params: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(paramsText) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        setMessage("Params must be a JSON object.");
        return;
      }
      params = parsed as Record<string, unknown>;
    } catch {
      setMessage("Params must be valid JSON.");
      return;
    }
    if (requiresClientScope) params = { ...params, client_id: selectedClientId };

    try {
      const body: ScheduledJobRequestBody = scheduleKind === "playbook"
        ? { playbook_id: playbookId, cron, timezone: timezone.trim(), params }
        : scheduleKind === "agent"
        ? { agent_id: agentId, entity_id: entityId.trim(), cron, timezone: timezone.trim(), params }
        : scheduleKind === "report"
          ? { report_type: reportType, cron, timezone: timezone.trim(), params }
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
        <form id="scheduled-job-form" className="draft-form" onSubmit={createJob}>
          <div className="grid">
            <label>
              Schedule type
              <select value={scheduleKind} onChange={(event) => setScheduleKind(event.target.value as "workflow" | "playbook" | "agent" | "report")}>
                <option value="workflow">Workflow template</option>
                <option value="playbook">MSP playbook</option>
                <option value="agent">Agent definition</option>
                <option value="report">Client report</option>
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
            ) : scheduleKind === "playbook" ? (
              <label>
                Playbook
                <select value={playbookId} onChange={(event) => setPlaybookId(event.target.value)}>
                  <option value="">Choose playbook</option>
                  {playbooks.map((playbook) => <option key={playbook.id} value={playbook.id}>{playbook.name}</option>)}
                </select>
              </label>
            ) : scheduleKind === "report" ? (
              <label>
                Report
                <select value={reportType} onChange={(event) => setReportType(event.target.value as "qbr" | "automation_opportunity" | "recurring_service_review")}>
                  <option value="qbr">Quarterly business review</option>
                  <option value="automation_opportunity">Automation opportunities</option>
                  <option value="recurring_service_review">Recurring service review</option>
                </select>
              </label>
            ) : (
              <>
                {agents.filter((agent) => agent.trigger === "scheduled" && agent.enabled).length === 0 ? <EmptyState title="No scheduled agents available" why="Agents exist, but none are scheduled and enabled. Enable an agent with a scheduled trigger before creating an agent schedule." /> : <label>
                  Agent
                  <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
                    <option value="">Choose scheduled agent</option>
                    {agents.filter((agent) => agent.trigger === "scheduled" && agent.enabled).map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </label>}
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
            {scheduleKind === "playbook" || scheduleKind === "report" ? <ClientIdSelect label="Client ID" value={selectedClientId} onChange={setSelectedClientId} clients={clients} required id="scheduled-job-client-id" /> : null}
            {scheduleKind === "playbook" ? <span className="field-help">The selected client is added automatically; params may include ticket_id and input.</span> : null}
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
              <textarea
                aria-label="Params JSON"
                rows={5}
                value={paramsText}
                onChange={(event) => setParamsText(event.target.value)}
              />
              {scheduleKind === "report" ? <span>The selected client is added automatically; include period_days (1–366) or period_start/period_end ISO dates.</span> : null}
            </label>
          </div>
          {(scheduleKind === "playbook" || scheduleKind === "report") && !selectedClientId ? <p className="screen-note">Select a client from the top bar before creating this schedule.</p> : null}
          <button type="submit" disabled={!canWrite || ((scheduleKind === "playbook" || scheduleKind === "report") && !selectedClientId)} title={!canWrite ? "Requires technician access" : (scheduleKind === "playbook" || scheduleKind === "report") && !selectedClientId ? "Select a client from the top bar first" : undefined}>Create schedule</button>
        </form>

        {message ? <div className="notice">{message}</div> : null}
        {loading ? <LoadingState label="Loading scheduled jobs…" /> : jobs.length === 0 ? <EmptyState title="No scheduled jobs yet" why="Scheduled jobs appear after you create a workflow, agent, or report schedule above." action={{ label: "Create a schedule above", to: "#scheduled-job-form" }} /> : <div className="table-list">
          {jobs.map((job) => (
            <article className="table-row" key={job.id}>
              <div>
                <strong>{jobTargetLabel(job)}</strong>
                <span>{job.cron} ({job.timezone})</span>
              </div>
              <span>{job.paused ? "paused" : "running"}</span>
              <div>
                <button className="icon-button" type="button" onClick={() => setSelectedJob(job)}>Details</button>
                <button className="icon-button" type="button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => void controlJob(job.paused ? "resume" : "pause", job.id)}>
                  {job.paused ? "Resume" : "Pause"}
                </button>
                <button className="icon-button" type="button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => void controlJob("delete", job.id)}>
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>}
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Job detail</h2>
          <span>{selectedJob ? `Job ${selectedJob.id}` : "no job selected"}</span>
        </div>
        {selectedJob ? (
          <>
            <div className="event-row">
              <span>{jobTargetLabel(selectedJob)}</span>
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

function jobTargetLabel(job: ScheduledJob): string {
  if (job.job_kind === "agent") return `Agent ${job.agent_id}`;
  if (job.job_kind === "report") return `Report ${job.template_id}`;
  if (job.job_kind === "playbook") return `Playbook ${job.playbook_id ?? job.template_id}`;
  return `Workflow ${job.template_id}`;
}
