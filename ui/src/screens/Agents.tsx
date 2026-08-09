import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import type { AgentDefinition, AgentPlan, AgentRunDetail, AgentTool } from "../api/types";

const contextOptions = [
  ["ticket", "Ticket details"],
  ["client", "Client identity"],
  ["knowledge", "Local knowledge"]
] as const;

export function Agents() {
  const { canWrite } = useDashboard();
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [clientId, setClientId] = useState("");
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [contextSources, setContextSources] = useState<string[]>(["ticket"]);
  const [approvalExpiryHours, setApprovalExpiryHours] = useState("");
  const [resultAware, setResultAware] = useState(false);
  const [ticketIds, setTicketIds] = useState<Record<string, string>>({});
  const [runDetails, setRunDetails] = useState<Record<string, AgentRunDetail>>({});
  const [message, setMessage] = useState("");
  const [planInstruction, setPlanInstruction] = useState("");
  const [planTicket, setPlanTicket] = useState("");
  const [plan, setPlan] = useState<AgentPlan | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [agentRows, toolRows] = await Promise.all([
        apiFetch<AgentDefinition[]>("/agents"),
        apiFetch<AgentTool[]>("/tools")
      ]);
      setAgents(agentRows);
      setTools(toolRows);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load agents.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function toggleValue(values: string[], value: string): string[] {
    return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
  }

  async function createAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const boundedTools = selectedTools.slice(0, 8);
    if (!name.trim() || boundedTools.length === 0) {
      setMessage("Provide a name and select at least one tool.");
      return;
    }
    const parsedApprovalExpiryHours = approvalExpiryHours.trim()
      ? Number(approvalExpiryHours)
      : undefined;
    if (
      parsedApprovalExpiryHours !== undefined &&
      (!Number.isInteger(parsedApprovalExpiryHours) || parsedApprovalExpiryHours < 1 || parsedApprovalExpiryHours > 720)
    ) {
      setMessage("Approval deadline must be a whole number of hours from 1 to 720.");
      return;
    }
    try {
      await apiFetch<AgentDefinition>("/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description,
          enabled: true,
          trigger: "manual",
          entity_type: "ticket",
          filters: {},
          enabled_tools: boundedTools,
          steps: boundedTools.map((tool_id) => ({ tool_id, payload: {} })),
          max_steps: boundedTools.length,
          execution_timeout_seconds: 30,
          context_sources: contextSources,
          approval_expiry_seconds: parsedApprovalExpiryHours === undefined
            ? undefined
            : parsedApprovalExpiryHours * 60 * 60,
          result_aware: resultAware,
          client_id: clientId || undefined
        })
      });
      setName("");
      setDescription("");
      setResultAware(false);
      setMessage("Agent created.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create agent.");
    }
  }

  async function setEnabled(agent: AgentDefinition, enabled: boolean) {
    try {
      await apiFetch<AgentDefinition>(`/agents/${encodeURIComponent(agent.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...agent, enabled })
      });
      setMessage(`${agent.name} is now ${enabled ? "enabled" : "disabled"}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to change agent availability.");
    }
  }

  async function runAgent(agent: AgentDefinition) {
    const ticketId = ticketIds[agent.id]?.trim();
    if (!ticketId) {
      setMessage("Provide a ticket id before running an agent.");
      return;
    }
    try {
      const run = await apiFetch<{ run_id: number }>(`/agents/${encodeURIComponent(agent.id)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: ticketId })
      });
      const detail = await apiFetch<AgentRunDetail>(`/agent-runs/${run.run_id}`);
      setRunDetails((current) => ({ ...current, [agent.id]: detail }));
      setMessage(`Started ${agent.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to run agent.");
    }
  }

  async function previewPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!planInstruction.trim() || !planTicket.trim()) {
      setMessage("Provide an instruction and ticket id before previewing a plan.");
      return;
    }
    try {
      const result = await apiFetch<AgentPlan>("/agents/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: planInstruction.trim(), entity_id: planTicket.trim() })
      });
      setPlan(result);
      setMessage(result.status === "preview" ? "Plan preview ready for review." : result.blocked_reason);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to preview the plan.");
    }
  }

  async function createPlanDraft() {
    if (!plan?.definition) return;
    try {
      await apiFetch<AgentDefinition>("/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(plan.definition)
      });
      setMessage("Disabled agent draft created. Review it before enabling.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create the draft.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h2>Agents</h2><span>{agents.length} definitions</span></div>
        <p className="screen-note">Create bounded ticket agents from the existing tool catalog. Selected context is tenant-scoped and recorded with each run.</p>
        <form className="draft-form" onSubmit={createAgent}>
          <div className="grid">
            <label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="MFA triage" /></label>
            <label>Client id (optional)<input value={clientId} onChange={(event) => setClientId(event.target.value)} /></label>
          </div>
          <label>Description<textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <label>Approval deadline (hours, optional)<input type="number" min="1" max="720" step="1" value={approvalExpiryHours} onChange={(event) => setApprovalExpiryHours(event.target.value)} placeholder="Tool default" /></label>
          <label><input type="checkbox" checked={resultAware} onChange={(event) => setResultAware(event.target.checked)} /> Continue from each approved result using the bounded catalog</label>
          <fieldset className="agent-option-group"><legend>Context sources</legend>{contextOptions.map(([value, label]) => <label key={value}><input type="checkbox" checked={contextSources.includes(value)} onChange={() => setContextSources((current) => toggleValue(current, value))} />{label}</label>)}</fieldset>
          <fieldset className="agent-option-group"><legend>Enabled tools (maximum 8 steps)</legend>{tools.map((tool) => {
            const selected = selectedTools.includes(tool.id);
            const atLimit = selectedTools.length >= 8;
            return <label key={tool.id}><input type="checkbox" checked={selected} disabled={!selected && atLimit} onChange={() => {
              if (!selected && atLimit) {
                setMessage("An agent can contain at most 8 tools.");
                return;
              }
              setSelectedTools((current) => toggleValue(current, tool.id));
            }} />{tool.name}{tool.approval_required ? " · approval" : ""}</label>;
          })}</fieldset>
          <button type="submit" disabled={!canWrite}>Create agent</button>
        </form>
        {message ? <div className="notice">{message}</div> : null}
      </section>

      <section className="agent-grid">
        {agents.length === 0 ? <p className="panel">No agents yet.</p> : null}
        {agents.map((agent) => {
          const detail = runDetails[agent.id];
          return <article className="panel agent-card" key={agent.id}>
            <div className="panel-heading"><h3>{agent.name}</h3><span>v{agent.version} · {agent.enabled ? "enabled" : "disabled"}</span></div>
            <p className="screen-note">{agent.description || "No description"}</p>
            <p className="screen-note">Context: {agent.context_sources.join(", ") || "none"}</p>
            <p className="screen-note">Tools: {agent.enabled_tools.join(", ")}</p>
            <p className="screen-note">Approval deadline: {agent.approval_expiry_seconds ? `${agent.approval_expiry_seconds / 3600} hours maximum` : "tool default"}</p>
            <p className="screen-note">Continuation: {agent.result_aware ? "result-aware, bounded" : "reviewed sequence"}</p>
            <div className="agent-run-row"><input aria-label={`Ticket for ${agent.name}`} value={ticketIds[agent.id] ?? ""} onChange={(event) => setTicketIds((current) => ({ ...current, [agent.id]: event.target.value }))} placeholder="Ticket id" /><button type="button" disabled={!canWrite || !agent.enabled} onClick={() => void runAgent(agent)}>Run</button><button type="button" disabled={!canWrite} onClick={() => void setEnabled(agent, !agent.enabled)}>{agent.enabled ? "Disable" : "Enable"}</button></div>
            {detail ? <div className="agent-run-detail"><strong>Run {detail.id}: {detail.status}</strong><span>Revision {detail.revision_version ?? "n/a"}</span><span>Context loaded: {Object.keys(detail.state?.context ?? {}).join(", ") || "none"}</span></div> : null}
          </article>;
        })}
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Plan preview</h2><span>Review only</span></div>
        <p className="screen-note">Describe a bounded ticket task. WAIT selects only existing tools and does not execute or publish this preview.</p>
        <form className="draft-form" onSubmit={(event) => void previewPlan(event)}>
          <div className="grid">
            <label>Ticket<input value={planTicket} onChange={(event) => setPlanTicket(event.target.value)} placeholder="TCK-1001" /></label>
            <label>Instruction<textarea rows={2} value={planInstruction} onChange={(event) => setPlanInstruction(event.target.value)} placeholder="Triage this ticket, search the runbook, and suggest a resolution." maxLength={2000} /></label>
          </div>
          <button type="submit" disabled={!canWrite}>Preview plan</button>
        </form>
        {plan ? <div className="agent-run-detail" aria-live="polite">
          <strong>{plan.status === "preview" ? `${plan.steps.length} approved tool step(s) proposed` : "Plan blocked"}</strong>
          <span>Selection: {plan.selection_mode === "model" ? "configured local model" : "deterministic rules"}</span>
          {plan.steps.map((step) => <div key={`${step.index}-${step.tool_id}`}><span>{step.index + 1}. {step.name}</span><small>{step.reason} {step.approval_required ? "Approval required." : "Read-only or draft."}</small></div>)}
          {plan.status === "preview" ? <button type="button" disabled={!canWrite} onClick={() => void createPlanDraft()}>Create disabled draft</button> : null}
          {plan.blocked_reason ? <p className="notice danger">{plan.blocked_reason}</p> : null}
        </div> : null}
      </section>
    </div>
  );
}
