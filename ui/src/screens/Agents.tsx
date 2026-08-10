import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import type { AgentApprovalRule, AgentDefinition, AgentPlan, AgentRevision, AgentRevisionDiff, AgentRunDetail, AgentTool } from "../api/types";

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
  const [stepPayloads, setStepPayloads] = useState<Record<string, string>>({});
  const [contextSources, setContextSources] = useState<string[]>(["ticket"]);
  const [approvalExpiryHours, setApprovalExpiryHours] = useState("");
  const [approvalRequiredTools, setApprovalRequiredTools] = useState<string[]>([]);
  const [approvalRuleDrafts, setApprovalRuleDrafts] = useState<Record<string, { priority: string; status: string; actor_role: string }>>({});
  const [resultAware, setResultAware] = useState(false);
  const [ticketIds, setTicketIds] = useState<Record<string, string>>({});
  const [runDetails, setRunDetails] = useState<Record<string, AgentRunDetail>>({});
  const [message, setMessage] = useState("");
  const [planInstruction, setPlanInstruction] = useState("");
  const [planTicket, setPlanTicket] = useState("");
  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [editingAgentId, setEditingAgentId] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<Record<string, AgentRevision[]>>({});
  const [diffs, setDiffs] = useState<Record<string, AgentRevisionDiff>>({});

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

  function resetAgentForm() {
    setEditingAgentId(null);
    setName("");
    setDescription("");
    setClientId("");
    setSelectedTools([]);
    setStepPayloads({});
    setContextSources(["ticket"]);
    setApprovalExpiryHours("");
    setApprovalRequiredTools([]);
    setApprovalRuleDrafts({});
    setResultAware(false);
  }

  function editAgent(agent: AgentDefinition) {
    setEditingAgentId(agent.id);
    setName(agent.name);
    setDescription(agent.description);
    setClientId(agent.client_id ?? "");
    setSelectedTools(agent.enabled_tools.slice(0, 8));
    setStepPayloads(Object.fromEntries(agent.steps.map((step) => [step.tool_id, JSON.stringify(step.payload, null, 2)])));
    setContextSources(agent.context_sources.length ? agent.context_sources : ["ticket"]);
    setApprovalExpiryHours(agent.approval_expiry_seconds ? String(agent.approval_expiry_seconds / 3600) : "");
    setApprovalRequiredTools(agent.approval_required_tools ?? []);
    setApprovalRuleDrafts(Object.fromEntries((agent.approval_rules ?? []).map((rule) => [rule.tool_id, {
      priority: rule.when.priority?.join(", ") ?? "",
      status: rule.when.status?.join(", ") ?? "",
      actor_role: rule.when.actor_role?.join(", ") ?? ""
    }])));
    setResultAware(agent.result_aware);
    setMessage(`Editing ${agent.name} version ${agent.version}. Save to create a new version.`);
  }

  function agentPayload(agent?: AgentDefinition) {
    const boundedTools = selectedTools.slice(0, 8);
    const parsedStepPayloads = Object.fromEntries(boundedTools.map((tool_id) => {
      const raw = stepPayloads[tool_id]?.trim() || "{}";
      const parsed = JSON.parse(raw) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error(`${tool_id} input must be a JSON object.`);
      }
      return [tool_id, parsed as Record<string, unknown>];
    }));
    const parsedApprovalExpiryHours = approvalExpiryHours.trim()
      ? Number(approvalExpiryHours)
      : undefined;
    const approval_rules: AgentApprovalRule[] = boundedTools.flatMap((tool_id) => {
      const draft = approvalRuleDrafts[tool_id];
      if (!draft) return [];
      const when: AgentApprovalRule["when"] = {};
      const priorities = draft.priority.split(",").map((value) => value.trim()).filter(Boolean);
      const statuses = draft.status.split(",").map((value) => value.trim()).filter(Boolean);
      const actorRoles = draft.actor_role.split(",").map((value) => value.trim()).filter(Boolean);
      if (priorities.length) when.priority = priorities;
      if (statuses.length) when.status = statuses;
      if (actorRoles.length) when.actor_role = actorRoles;
      return Object.keys(when).length ? [{ tool_id, when }] : [];
    });
    return {
      name: name.trim(),
      description,
      enabled: agent?.enabled ?? true,
      trigger: agent?.trigger ?? "manual",
      entity_type: agent?.entity_type ?? "ticket",
      filters: agent?.filters ?? {},
      enabled_tools: boundedTools,
      steps: boundedTools.map((tool_id) => ({ tool_id, payload: parsedStepPayloads[tool_id] ?? agent?.steps.find((step) => step.tool_id === tool_id)?.payload ?? {} })),
      max_steps: boundedTools.length,
      execution_timeout_seconds: agent?.execution_timeout_seconds ?? 30,
      context_sources: contextSources,
      approval_expiry_seconds: parsedApprovalExpiryHours === undefined
        ? undefined
        : parsedApprovalExpiryHours * 60 * 60,
      approval_required_tools: approvalRequiredTools.filter((tool_id) => boundedTools.includes(tool_id)),
      approval_rules,
      result_aware: resultAware,
      client_id: clientId || undefined,
      run_once_per_entity: agent?.run_once_per_entity ?? true,
      depends_on_agent_ids: agent?.depends_on_agent_ids ?? [],
      execution_window_start: agent?.execution_window_start,
      execution_window_end: agent?.execution_window_end,
      execution_window_timezone: agent?.execution_window_timezone ?? "UTC"
    };
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
    const existing = editingAgentId ? agents.find((agent) => agent.id === editingAgentId) : undefined;
    if (editingAgentId && !existing) {
      setMessage("This agent is no longer available. Refresh the list before saving.");
      return;
    }
    try {
      agentPayload(existing);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Each tool input must be a JSON object.");
      return;
    }
    try {
      await apiFetch<AgentDefinition>(existing ? `/agents/${encodeURIComponent(existing.id)}` : "/agents", {
        method: existing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(agentPayload(existing))
      });
      const action = existing ? "updated" : "created";
      resetAgentForm();
      setMessage(existing ? `Agent ${action}; a new revision is now available.` : "Agent created.");
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

  async function showRevisions(agent: AgentDefinition) {
    try {
      const rows = await apiFetch<AgentRevision[]>(`/agents/${encodeURIComponent(agent.id)}/revisions`);
      setRevisions((current) => ({ ...current, [agent.id]: rows }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load agent history.");
    }
  }

  async function compareRevision(agent: AgentDefinition, version: number) {
    try {
      const diff = await apiFetch<AgentRevisionDiff>(
        `/agents/${encodeURIComponent(agent.id)}/revisions/${version}/diff/${agent.version}`
      );
      setDiffs((current) => ({ ...current, [agent.id]: diff }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to compare agent history.");
    }
  }

  async function restoreRevision(agent: AgentDefinition, version: number) {
    try {
      const restored = await apiFetch<AgentDefinition>(
        `/agents/${encodeURIComponent(agent.id)}/revisions/${version}/restore`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      setAgents((current) => current.map((item) => item.id === restored.id ? restored : item));
      setMessage(`Restored ${agent.name} version ${version} as version ${restored.version}.`);
      await showRevisions(restored);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to restore agent history.");
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
        <p className="screen-note">Create and review bounded ticket agents from the existing tool catalog. Saving an existing agent creates a recoverable revision; selected context is tenant-scoped and recorded with each run.</p>
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
              if (!selected && !stepPayloads[tool.id]) {
                setStepPayloads((current) => ({ ...current, [tool.id]: "{}" }));
              }
              if (selected) {
                setApprovalRequiredTools((current) => current.filter((value) => value !== tool.id));
              }
            }} />{tool.name}{tool.approval_required ? " · approval" : ""}</label>;
          })}</fieldset>
          <fieldset className="agent-option-group"><legend>Tool inputs (JSON objects)</legend><p className="screen-note">Provide the bounded inputs each selected tool needs. The ticket id is added automatically when a tool supports it; client-scoped tools can use the agent's client mapping.</p>{tools.filter((tool) => selectedTools.includes(tool.id)).map((tool) => <label key={`payload-${tool.id}`}>{tool.name}<textarea aria-label={`${tool.name} input JSON`} rows={4} value={stepPayloads[tool.id] ?? "{}"} onChange={(event) => setStepPayloads((current) => ({ ...current, [tool.id]: event.target.value }))} /></label>)}</fieldset>
          <fieldset className="agent-option-group"><legend>Additional approval rules</legend><p className="screen-note">Require approval for selected tools even when their catalog policy is read-only. Built-in approval requirements cannot be disabled.</p>{tools.filter((tool) => selectedTools.includes(tool.id)).map((tool) => <label key={`approval-${tool.id}`}><input type="checkbox" checked={approvalRequiredTools.includes(tool.id)} onChange={() => setApprovalRequiredTools((current) => toggleValue(current, tool.id))} />{tool.name}{tool.approval_required ? " · already required" : " · require approval"}</label>)}</fieldset>
          <fieldset className="agent-option-group"><legend>Conditional approval rules</legend><p className="screen-note">Require approval only when the ticket matches explicit priority, status, or requester-role values. Enter comma-separated values; matches are case-insensitive and all entered fields must match. Scheduled and event runs have no authenticated requester role, so a role condition does not match them.</p>{tools.filter((tool) => selectedTools.includes(tool.id)).map((tool) => {
            const draft = approvalRuleDrafts[tool.id] ?? { priority: "", status: "", actor_role: "" };
            return <div className="agent-rule-row" key={`conditional-${tool.id}`}><strong>{tool.name}</strong><label>Priority values<input aria-label={`${tool.name} priority conditions`} value={draft.priority} onChange={(event) => setApprovalRuleDrafts((current) => ({ ...current, [tool.id]: { ...draft, priority: event.target.value } }))} placeholder="urgent, high" /></label><label>Status values<input aria-label={`${tool.name} status conditions`} value={draft.status} onChange={(event) => setApprovalRuleDrafts((current) => ({ ...current, [tool.id]: { ...draft, status: event.target.value } }))} placeholder="new, open" /></label><label>Requester roles<input aria-label={`${tool.name} requester role conditions`} value={draft.actor_role} onChange={(event) => setApprovalRuleDrafts((current) => ({ ...current, [tool.id]: { ...draft, actor_role: event.target.value } }))} placeholder="technician, viewer" /></label></div>;
          })}</fieldset>
          <div className="row-actions">
            <button type="submit" disabled={!canWrite}>{editingAgentId ? "Save agent revision" : "Create agent"}</button>
            {editingAgentId ? <button type="button" className="secondary-button" onClick={resetAgentForm}>Cancel edit</button> : null}
          </div>
        </form>
        {message ? <div className="notice">{message}</div> : null}
      </section>

      <section className="agent-grid">
        {agents.length === 0 ? <p className="panel">No agents yet.</p> : null}
        {agents.map((agent) => {
          const detail = runDetails[agent.id];
          const additionalApprovalTools = agent.approval_required_tools ?? [];
          const conditionalApprovalRules = (agent.approval_rules ?? []).map((rule) => `${rule.tool_id} (${Object.entries(rule.when).map(([field, values]) => `${field}=${values.join("|")}`).join(", ")})`);
          return <article className="panel agent-card" key={agent.id}>
            <div className="panel-heading"><h3>{agent.name}</h3><span>v{agent.version} · {agent.enabled ? "enabled" : "disabled"}</span></div>
            <p className="screen-note">{agent.description || "No description"}</p>
            <p className="screen-note">Context: {agent.context_sources.join(", ") || "none"}</p>
            <p className="screen-note">Tools: {agent.enabled_tools.join(", ")}</p>
            <p className="screen-note">Approval deadline: {agent.approval_expiry_seconds ? `${agent.approval_expiry_seconds / 3600} hours maximum` : "tool default"}</p>
            <p className="screen-note">Additional approval: {additionalApprovalTools.length ? additionalApprovalTools.join(", ") : "none"}</p>
            <p className="screen-note">Conditional approval: {conditionalApprovalRules.length ? conditionalApprovalRules.join("; ") : "none"}</p>
            <p className="screen-note">Continuation: {agent.result_aware ? "result-aware, bounded" : "reviewed sequence"}</p>
            <div className="agent-run-row"><input aria-label={`Ticket for ${agent.name}`} value={ticketIds[agent.id] ?? ""} onChange={(event) => setTicketIds((current) => ({ ...current, [agent.id]: event.target.value }))} placeholder="Ticket id" /><button type="button" disabled={!canWrite || !agent.enabled} onClick={() => void runAgent(agent)}>Run</button><button type="button" disabled={!canWrite} onClick={() => void setEnabled(agent, !agent.enabled)}>{agent.enabled ? "Disable" : "Enable"}</button><button type="button" disabled={!canWrite} onClick={() => editAgent(agent)}>Edit</button><button type="button" className="secondary-button" onClick={() => void showRevisions(agent)}>History</button></div>
            {revisions[agent.id] ? <div className="agent-history" aria-live="polite"><strong>Revision history</strong>{revisions[agent.id].map((revision) => <div className="agent-history-row" key={`${agent.id}-${revision.version}`}><span>Version {revision.version} · {revision.created_at}</span><div className="row-actions">{revision.version !== agent.version ? <><button type="button" className="secondary-button" onClick={() => void compareRevision(agent, revision.version)}>Compare to current</button><button type="button" className="secondary-button" disabled={!canWrite} onClick={() => void restoreRevision(agent, revision.version)}>Restore</button></> : <span>current</span>}</div></div>)}{diffs[agent.id] ? <div className="agent-diff"><strong>{diffs[agent.id].changed ? "Changes" : "No changes"}</strong>{diffs[agent.id].changes.length ? diffs[agent.id].changes.map((change) => <div key={change.field}><span>{change.field}</span><small>{JSON.stringify(change.before)} → {JSON.stringify(change.after)}</small></div>) : <span>No persisted fields differ.</span>}</div> : null}</div> : null}
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
