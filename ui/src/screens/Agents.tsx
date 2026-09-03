import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { AgentToolPicker } from "../components/AgentToolPicker";
import { ScopeBadge } from "../components/ScopeBadge";
import { SelectClientNotice } from "../components/SelectClientNotice";
import type { AgentApprovalRule, AgentDefinition, AgentFailurePolicy, AgentPlan, AgentRevision, AgentRevisionDiff, AgentRunDetail, AgentTool } from "../api/types";

type RevisionSelection = {
  fromVersion: string;
  toVersion: string;
};

type RestoreRequest = {
  agentId: string;
  version: number;
};

const contextOptions = [
  ["ticket", "Ticket details"],
  ["client", "Client identity"],
  ["knowledge", "Local knowledge"]
] as const;

const failurePolicyModes: Array<[AgentFailurePolicy["mode"], string]> = [
  ["stop", "Stop and record failure"],
  ["retry", "Retry this step"],
  ["fallback", "Use configured fallback"],
  ["human_input", "Request human input"],
  ["technician_escalation", "Escalate to technician"],
  ["blocked", "Block for review"]
];

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? String(value);
}

function renderDiffValue(value: unknown): string {
  return typeof value === "string" ? value : jsonText(value);
}

export function Agents() {
  const { canWrite, clients = [], connectors = [], selectedClientId = "", isMspAdmin = false } = useDashboard();
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [stepPayloads, setStepPayloads] = useState<Record<string, string>>({});
  const [failurePolicyDrafts, setFailurePolicyDrafts] = useState<Record<string, AgentFailurePolicy>>({});
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
  const [revisionSelections, setRevisionSelections] = useState<Record<string, RevisionSelection>>({});
  const [confirmingRestore, setConfirmingRestore] = useState<RestoreRequest | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [agentRows, toolRows] = await Promise.all([
        apiFetch<AgentDefinition[]>("/agents"),
        apiFetch<AgentTool[]>("/tools")
      ]);
      setAgents(agentRows);
      setTools(toolRows);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load agents.");
    } finally {
      setLoading(false);
    }
  }, [selectedClientId]);

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
    setSelectedTools([]);
    setStepPayloads({});
    setFailurePolicyDrafts({});
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
    setSelectedTools(agent.enabled_tools.slice(0, 8));
    setStepPayloads(Object.fromEntries(agent.steps.map((step) => [step.tool_id, JSON.stringify(step.payload, null, 2)])));
    setFailurePolicyDrafts(Object.fromEntries(agent.steps.map((step) => [step.tool_id, step.failure_policy ?? { mode: "stop" }] )));
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
      steps: boundedTools.map((tool_id) => {
        const policy = failurePolicyDrafts[tool_id] ?? { mode: "stop" as const };
        const failure_policy = policy.mode === "stop"
          ? undefined
          : {
              mode: policy.mode,
              ...(policy.mode === "retry" ? { max_retries: Math.min(3, Math.max(1, policy.max_retries ?? 1)) } : {}),
              ...(policy.mode === "fallback" ? { fallback_tool_id: policy.fallback_tool_id ?? "" } : {})
            };
        return {
          tool_id,
          payload: parsedStepPayloads[tool_id] ?? agent?.steps.find((step) => step.tool_id === tool_id)?.payload ?? {},
          ...(failure_policy ? { failure_policy } : {})
        };
      }),
      max_steps: boundedTools.length,
      execution_timeout_seconds: agent?.execution_timeout_seconds ?? 30,
      context_sources: contextSources,
      approval_expiry_seconds: parsedApprovalExpiryHours === undefined
        ? undefined
        : parsedApprovalExpiryHours * 60 * 60,
      approval_required_tools: approvalRequiredTools.filter((tool_id) => boundedTools.includes(tool_id)),
      approval_rules,
      result_aware: resultAware,
      client_id: selectedClientId || undefined,
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
      setRevisionSelections((current) => ({
        ...current,
        [agent.id]: { fromVersion: "", toVersion: "" }
      }));
      setDiffs((current) => {
        const next = { ...current };
        delete next[agent.id];
        return next;
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load agent history.");
    }
  }

  async function compareRevisions(agent: AgentDefinition) {
    const selection = revisionSelections[agent.id];
    if (!selection?.fromVersion || !selection.toVersion || selection.fromVersion === selection.toVersion) {
      return;
    }
    try {
      const diff = await apiFetch<AgentRevisionDiff>(
        `/agents/${encodeURIComponent(agent.id)}/revisions/${encodeURIComponent(selection.fromVersion)}/diff/${encodeURIComponent(selection.toVersion)}`
      );
      setDiffs((current) => ({ ...current, [agent.id]: diff }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to compare agent history.");
    }
  }

  function requestRestore(agent: AgentDefinition, version: number) {
    if (!canWrite) return;
    setConfirmingRestore({ agentId: agent.id, version });
  }

  async function confirmRestore(agent: AgentDefinition, version: number) {
    if (!canWrite) return;
    const wasEditing = editingAgentId === agent.id;
    setConfirmingRestore(null);
    try {
      const restored = await apiFetch<AgentDefinition>(
        `/agents/${encodeURIComponent(agent.id)}/revisions/${version}/restore`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      await refresh();
      if (wasEditing) {
        editAgent(restored);
      }
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

  async function controlRun(agent: AgentDefinition, detail: AgentRunDetail, action: "cancel" | "retry") {
    try {
      const result = await apiFetch<{ run_id: number }>(`/agent-runs/${detail.id}/${action}`, { method: "POST" });
      const targetRunId = action === "retry" ? result.run_id : detail.id;
      const updated = await apiFetch<AgentRunDetail>(`/agent-runs/${targetRunId}`);
      setRunDetails((current) => ({ ...current, [agent.id]: updated }));
      setMessage(action === "retry" ? `Retried ${agent.name}; the new run is recorded with its parent.` : `Cancelled run ${detail.id}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `Unable to ${action} the agent run.`);
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
        <form id="agent-form" className="draft-form" onSubmit={createAgent}>
          <div className="grid">
            <label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="MFA triage" /></label>
            <p className="screen-note">Scope: <ScopeBadge /></p>
          </div>
          <label>Description<textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <label>Approval deadline (hours, optional)<input type="number" min="1" max="720" step="1" value={approvalExpiryHours} onChange={(event) => setApprovalExpiryHours(event.target.value)} placeholder="Tool default" /></label>
          <label><input type="checkbox" checked={resultAware} onChange={(event) => setResultAware(event.target.checked)} /> Continue from each approved result using the bounded catalog</label>
          <fieldset className="agent-option-group"><legend>Context sources</legend>{contextOptions.map(([value, label]) => <label key={value}><input type="checkbox" checked={contextSources.includes(value)} onChange={() => setContextSources((current) => toggleValue(current, value))} />{label}</label>)}</fieldset>
          <fieldset className="agent-option-group">
            <legend><span>Enabled tools (maximum 8 steps)</span><span aria-live="polite">{selectedTools.length} of 8 tools selected</span></legend>
            {loading ? <LoadingState label="Loading tool catalog…" /> : tools.length === 0 ? <EmptyState title="No tools are available" why="The local tool catalog returned no tools to include in an agent." /> : (
              <AgentToolPicker
                tools={tools}
                selectedTools={selectedTools}
                connectors={connectors}
                onLimitReached={() => setMessage("An agent can contain at most 8 tools.")}
                onToggle={(tool) => {
                  const selected = selectedTools.includes(tool.id);
                  setSelectedTools((current) => toggleValue(current, tool.id));
                  if (!selected && !stepPayloads[tool.id]) {
                    setStepPayloads((current) => ({ ...current, [tool.id]: "{}" }));
                  }
                  if (selected) {
                    setApprovalRequiredTools((current) => current.filter((value) => value !== tool.id));
                  }
                }}
              />
            )}
          </fieldset>
          <fieldset className="agent-option-group"><legend>Tool inputs (JSON objects)</legend><p className="screen-note">Provide the bounded inputs each selected tool needs. The ticket id is added automatically when a tool supports it; client-scoped tools can use the agent's client mapping.</p>{tools.filter((tool) => selectedTools.includes(tool.id)).map((tool) => <label key={`payload-${tool.id}`}>{tool.name}<textarea aria-label={`${tool.name} input JSON`} rows={4} value={stepPayloads[tool.id] ?? "{}"} onChange={(event) => setStepPayloads((current) => ({ ...current, [tool.id]: event.target.value }))} /></label>)}</fieldset>
          <fieldset className="agent-option-group"><legend>Failure handling</legend><p className="screen-note">Failure policies are deterministic and bounded. Retries are limited to three attempts; fallbacks must be another selected tool. Human-input, technician-escalation, and blocked modes stop the run with an explicit recovery state.</p>{tools.filter((tool) => selectedTools.includes(tool.id)).map((tool) => {
            const draft = failurePolicyDrafts[tool.id] ?? { mode: "stop" as const };
            return <div className="agent-rule-row" key={`failure-${tool.id}`}><strong>{tool.name}</strong><label>On failure<select aria-label={`${tool.name} failure policy`} value={draft.mode} onChange={(event) => setFailurePolicyDrafts((current) => ({ ...current, [tool.id]: { ...draft, mode: event.target.value as AgentFailurePolicy["mode"] } }))}>{failurePolicyModes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>{draft.mode === "retry" ? <label>Retries<input type="number" min="1" max="3" step="1" value={draft.max_retries ?? 1} onChange={(event) => setFailurePolicyDrafts((current) => ({ ...current, [tool.id]: { ...draft, max_retries: Number(event.target.value) } }))} /></label> : null}{draft.mode === "fallback" ? <label>Fallback tool<select aria-label={`${tool.name} fallback tool`} value={draft.fallback_tool_id ?? ""} onChange={(event) => setFailurePolicyDrafts((current) => ({ ...current, [tool.id]: { ...draft, fallback_tool_id: event.target.value } }))}><option value="">Choose selected tool</option>{selectedTools.filter((candidate) => candidate !== tool.id).map((candidate) => <option key={candidate} value={candidate}>{tools.find((item) => item.id === candidate)?.name ?? candidate}</option>)}</select></label> : null}</div>;
          })}</fieldset>
          <fieldset className="agent-option-group"><legend>Additional approval rules</legend><p className="screen-note">Require approval for selected tools even when their catalog policy is read-only. Built-in approval requirements cannot be disabled.</p>{tools.filter((tool) => selectedTools.includes(tool.id)).map((tool) => <label key={`approval-${tool.id}`}><input type="checkbox" checked={approvalRequiredTools.includes(tool.id)} onChange={() => setApprovalRequiredTools((current) => toggleValue(current, tool.id))} />{tool.name}{tool.approval_required ? " · already required" : " · require approval"}</label>)}</fieldset>
          <fieldset className="agent-option-group"><legend>Conditional approval rules</legend><p className="screen-note">Require approval only when the ticket matches explicit priority, status, or requester-role values. Enter comma-separated values; matches are case-insensitive and all entered fields must match. Scheduled and event runs have no authenticated requester role, so a role condition does not match them.</p>{tools.filter((tool) => selectedTools.includes(tool.id)).map((tool) => {
            const draft = approvalRuleDrafts[tool.id] ?? { priority: "", status: "", actor_role: "" };
            return <div className="agent-rule-row" key={`conditional-${tool.id}`}><strong>{tool.name}</strong><label>Priority values<input aria-label={`${tool.name} priority conditions`} value={draft.priority} onChange={(event) => setApprovalRuleDrafts((current) => ({ ...current, [tool.id]: { ...draft, priority: event.target.value } }))} placeholder="urgent, high" /></label><label>Status values<input aria-label={`${tool.name} status conditions`} value={draft.status} onChange={(event) => setApprovalRuleDrafts((current) => ({ ...current, [tool.id]: { ...draft, status: event.target.value } }))} placeholder="new, open" /></label><label>Requester roles<input aria-label={`${tool.name} requester role conditions`} value={draft.actor_role} onChange={(event) => setApprovalRuleDrafts((current) => ({ ...current, [tool.id]: { ...draft, actor_role: event.target.value } }))} placeholder="technician, viewer" /></label></div>;
          })}</fieldset>
          <div className="row-actions">
            {!selectedClientId && !isMspAdmin ? <SelectClientNotice /> : null}
            <button type="submit" disabled={!canWrite || (!selectedClientId && !isMspAdmin)} title={!canWrite ? "Requires technician access" : !selectedClientId ? "Choose a client in the top bar first" : undefined}>{editingAgentId ? "Save agent revision" : "Create agent"}</button>
            {editingAgentId ? <button type="button" className="secondary-button" onClick={resetAgentForm}>Cancel edit</button> : null}
          </div>
        </form>
        {message ? <div className="notice">{message}</div> : null}
      </section>

      <section className="agent-grid">
        {loading ? <LoadingState label="Loading agent definitions…" /> : agents.length === 0 ? <EmptyState title="No agent definitions yet" why="A fresh workspace has no agent definitions. Create one from the bounded tool catalog above." action={{ label: "Create your first agent below", to: "#agent-form" }} /> : agents.map((agent) => {
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
            <div className="agent-run-row"><input aria-label={`Ticket for ${agent.name}`} value={ticketIds[agent.id] ?? ""} onChange={(event) => setTicketIds((current) => ({ ...current, [agent.id]: event.target.value }))} placeholder="Ticket id" /><button type="button" disabled={!canWrite || !agent.enabled} title={!canWrite ? "Requires technician access" : !agent.enabled ? "Enable this agent before running it" : undefined} onClick={() => void runAgent(agent)}>Run</button><button type="button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => void setEnabled(agent, !agent.enabled)}>{agent.enabled ? "Disable" : "Enable"}</button><button type="button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => editAgent(agent)}>Edit</button></div>
            <details className="agent-revisions-drawer">
              <summary onClick={() => { if (!revisions[agent.id]) void showRevisions(agent); }}>History and recovery</summary>
              {revisions[agent.id] ? (() => {
                const selection = revisionSelections[agent.id];
                const diff = diffs[agent.id];
                return <div className="event-list" aria-label={`Revisions for ${agent.name}`}>
                  <strong>Revision history</strong>
                  <div className="grid revision-selector">
                    <label>
                      From revision
                      <select
                        aria-label={`From revision for ${agent.name}`}
                        value={selection?.fromVersion ?? ""}
                        onChange={(event) => setRevisionSelections((current) => ({
                          ...current,
                          [agent.id]: { fromVersion: event.target.value, toVersion: selection?.toVersion ?? "" }
                        }))}
                      >
                        <option value="">Choose a version</option>
                        {revisions[agent.id].map((revision) => <option key={`from-${revision.version}`} value={revision.version}>Version {revision.version}</option>)}
                      </select>
                    </label>
                    <label>
                      To revision
                      <select
                        aria-label={`To revision for ${agent.name}`}
                        value={selection?.toVersion ?? ""}
                        onChange={(event) => setRevisionSelections((current) => ({
                          ...current,
                          [agent.id]: { fromVersion: selection?.fromVersion ?? "", toVersion: event.target.value }
                        }))}
                      >
                        <option value="">Choose a version</option>
                        {revisions[agent.id].map((revision) => <option key={`to-${revision.version}`} value={revision.version}>Version {revision.version}</option>)}
                      </select>
                    </label>
                    <button type="button" disabled={!selection?.fromVersion || !selection.toVersion || selection.fromVersion === selection.toVersion} onClick={() => void compareRevisions(agent)}>Compare revisions</button>
                  </div>
                  {revisions[agent.id].map((revision) => <article className="event-row" key={`${agent.id}-${revision.version}`}>
                    <span>Version {revision.version}</span>
                    <span>{revision.created_at}</span>
                    {revision.version !== agent.version ? <button type="button" className="secondary-button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => requestRestore(agent, revision.version)}>Restore</button> : <span>current</span>}
                  </article>)}
                  {confirmingRestore?.agentId === agent.id ? <div className="notice confirm-panel" role="alertdialog" aria-label="Confirm agent restore">
                    <p>Restore version {confirmingRestore.version} of {agent.name}? This creates a new current version.</p>
                    <div className="row-actions">
                      <button type="button" onClick={() => void confirmRestore(agent, confirmingRestore.version)}>Confirm restore</button>
                      <button type="button" className="icon-button" onClick={() => setConfirmingRestore(null)}>Cancel</button>
                    </div>
                  </div> : null}
                  {diff ? <div className="agent-diff" aria-label={`Revision diff for ${agent.name}`}>
                    <strong>Changes: v{diff.from_version} → v{diff.to_version}</strong>
                    {diff.changes.length === 0 ? <p>No changes.</p> : <ul>{diff.changes.map((change) => <li key={change.field}>
                      <code>{change.field}</code>
                      <div><span>Before</span><pre>{renderDiffValue(change.before)}</pre></div>
                      <div><span>After</span><pre>{renderDiffValue(change.after)}</pre></div>
                    </li>)}</ul>}
                  </div> : null}
                </div>;
              })() : <p className="screen-note">Loading history.</p>}
            </details>
            {detail ? <div className="agent-run-detail">
              <strong>Run {detail.id}: {detail.status}</strong>
              <span>Revision {detail.revision_version ?? "n/a"}</span>
              <span>Context loaded: {Object.keys(detail.state?.context ?? {}).join(", ") || "none"}</span>
              <span>History: {detail.lineage?.partial_history?.completed_steps ?? 0} of {detail.lineage?.partial_history?.attempted_steps ?? detail.state?.steps?.length ?? 0} step(s) completed{detail.lineage?.partial_history?.partial ? " before the failure" : ""}.</span>
              {detail.lineage?.retry_of_run_id ? <span>Retry of run {detail.lineage.retry_of_run_id} · attempt {detail.lineage.retry_count + 1}</span> : null}
              {detail.state?.final_result?.exception && typeof detail.state.final_result.exception === "object" ? <span>Recovery: {String((detail.state.final_result.exception as { kind?: unknown }).kind ?? "review required")} · {String((detail.state.final_result.exception as { next_action?: unknown }).next_action ?? "technician review")}</span> : null}
              {detail.state?.steps?.map((step, index) => <small key={`${detail.id}-step-${index}`}>Step {index + 1}: {String(step.tool_id ?? "unknown")} · {String(step.status ?? "unknown")}{step.attempt !== undefined ? ` · attempt ${String(step.attempt)}` : ""}{step.failure_policy && typeof step.failure_policy === "object" ? ` · policy ${String((step.failure_policy as { mode?: unknown }).mode ?? "stop")}` : ""}{step.error_detail ? ` · ${String(step.error_detail)}` : ""}</small>)}
              <div className="row-actions">
                {(detail.status === "queued" || detail.status === "pending_approval") ? <button type="button" className="secondary-button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => void controlRun(agent, detail, "cancel")}>Cancel run</button> : null}
                {(detail.status === "failed" || detail.status === "cancelled") ? <button type="button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => void controlRun(agent, detail, "retry")}>Retry run</button> : null}
              </div>
            </div> : null}
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
          <button type="submit" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined}>Preview plan</button>
        </form>
        {plan ? <div className="agent-run-detail" aria-live="polite">
          <strong>{plan.status === "preview" ? `${plan.steps.length} approved tool step(s) proposed` : "Plan blocked"}</strong>
          <span>Selection: {plan.selection_mode === "model" ? "configured local model" : "deterministic rules"}</span>
          {plan.steps.map((step) => <div key={`${step.index}-${step.tool_id}`}><span>{step.index + 1}. {step.name}</span><small>{step.reason} {step.approval_required ? "Approval required." : "Read-only or draft."}</small></div>)}
          {plan.status === "preview" ? <button type="button" disabled={!canWrite} title={!canWrite ? "Requires technician access" : undefined} onClick={() => void createPlanDraft()}>Create disabled draft</button> : null}
          {plan.blocked_reason ? <p className="notice danger">{plan.blocked_reason}</p> : null}
        </div> : null}
      </section>
    </div>
  );
}
