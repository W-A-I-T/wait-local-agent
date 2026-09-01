import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";

type PlatformTab = "memory" | "skills" | "iterations" | "technicians" | "attachments";

type PlatformStatus = {
  status: string;
  migration_version: number;
  capabilities: Record<string, boolean>;
  attachment_max_bytes: number;
  write_actions_enabled: boolean;
  llm_inference_enabled: boolean;
  initialized: boolean;
};

type MemoryRecord = {
  id: string;
  client_id: string;
  scope_type: string;
  scope_id: string;
  key: string;
  value: unknown;
  summary: string;
  provenance: string;
  pinned: boolean;
  status: string;
  version: number;
  updated_at: string;
};

type SkillRevision = {
  version: number;
  instructions: string;
  allowed_tools: string[];
  digest: string;
};

type SkillRecord = {
  id: string;
  name: string;
  slug: string;
  description: string;
  status: string;
  current_version: number;
  revision: SkillRevision;
};

type IterationEvent = {
  ordinal: number;
  event_type: string;
  status: string;
  tool_id?: string;
};

type IterationSession = {
  id: string;
  source_type: string;
  source_id: string;
  source_version: number;
  entity_id: string;
  status: string;
  current_step: number;
  steps: Array<{ tool_id: string; payload: Record<string, unknown> }>;
  approval_id?: number;
  events: IterationEvent[];
};

type AgentDefinition = {
  id: string;
  name: string;
  client_id?: string;
};

type TechnicianWorkload = {
  open_tickets: number;
  active_incidents: number;
  scheduled_changes: number;
  observed_at: string;
};

type TechnicianProfile = {
  technician_id: string;
  display_name: string;
  timezone: string;
  expertise: string[];
  client_familiarity: number;
  capacity: number;
  enabled: boolean;
  workload?: TechnicianWorkload;
};

type TechnicianRecommendation = {
  ticket_id: string;
  recommendation?: {
    technician_id: string;
    display_name: string;
    score: number;
    reasons: string[];
  } | null;
  candidates: Array<{
    technician_id: string;
    display_name: string;
    score: number;
  }>;
  side_effects: boolean;
};

type TicketAttachment = {
  id: string;
  ticket_id: string;
  filename: string;
  media_type: string;
  byte_size: number;
  sha256: string;
  created_at: string;
};

type AttachmentAnalysis = {
  id: number;
  attachment_id: string;
  status: string;
  provider: string;
  model: string;
  result: Record<string, unknown>;
  error_detail: string;
};

type SmartActionOption = {
  action_id: string;
  title: string;
  risk_level: string;
  requires_approval: boolean;
};

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

function splitValues(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))];
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

function StatusSummary({
  status,
  selectedClientId,
  clientName,
  liveWritesReady,
  writeHealthResolved
}: {
  status: PlatformStatus | null;
  selectedClientId: string;
  clientName?: string;
  liveWritesReady: boolean;
  writeHealthResolved: boolean;
}) {
  if (!status) return null;
  const enabled = Object.entries(status.capabilities).filter(([, value]) => value).length;
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Agent Platform</h2>
        <span>{status.initialized ? status.status : "initializing"}</span>
      </div>
      <p className="screen-note">
        Client scope: {selectedClientId ? `${clientName ?? "Selected client"} (${selectedClientId})` : "none selected"}.
        Local capability changes remain separate from live PSA writes.
      </p>
      <p className="screen-note">
        {enabled} governed capabilities are available. Executable steps continue to use the existing Smart Action,
        tenant, role, approval, and audit boundaries.
      </p>
      <div className="grid">
        <div><strong>Schema</strong><p>v{status.migration_version}</p></div>
        <div><strong>Live PSA writes</strong><p>{!writeHealthResolved ? "checking" : liveWritesReady ? "ready" : "blocked"}</p></div>
        <div><strong>Image inference</strong><p>{status.llm_inference_enabled ? "enabled" : "blocked"}</p></div>
      </div>
    </section>
  );
}

function MemoryPanel({ canWrite }: { canWrite: boolean }) {
  const [records, setRecords] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [scopeType, setScopeType] = useState("client");
  const [scopeId, setScopeId] = useState("");
  const [key, setKey] = useState("");
  const [value, setValue] = useState("{}");
  const [summary, setSummary] = useState("");
  const [provenance, setProvenance] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setRecords(await apiFetch<MemoryRecord[]>("/packs/agent-platform/memories"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load memories.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await apiFetch<MemoryRecord>("/packs/agent-platform/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope_type: scopeType,
          scope_id: scopeId,
          key,
          value: parseJsonObject(value, "Memory value"),
          summary,
          provenance
        })
      });
      setKey("");
      setSummary("");
      setProvenance("");
      setValue("{}");
      setMessage("Memory revision stored.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to store memory.");
    }
  }

  async function pin(record: MemoryRecord) {
    try {
      await apiFetch(`/packs/agent-platform/memories/${record.id}/pin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned: !record.pinned })
      });
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to update memory.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h3>Durable memory</h3><span>{records.length} active</span></div>
        <p className="screen-note">Store explicit tenant facts with provenance. Updating the same key creates a revision instead of overwriting history.</p>
        <form className="draft-form" onSubmit={create}>
          <div className="grid">
            <label>Scope<select value={scopeType} onChange={(event) => setScopeType(event.target.value)}><option value="client">Client</option><option value="agent">Agent</option><option value="technician">Technician</option><option value="ticket">Ticket</option></select></label>
            <label>Scope ID<input value={scopeId} disabled={scopeType === "client"} onChange={(event) => setScopeId(event.target.value)} /></label>
            <label>Key<input required value={key} onChange={(event) => setKey(event.target.value)} /></label>
          </div>
          <label>JSON value<textarea required rows={4} value={value} onChange={(event) => setValue(event.target.value)} /></label>
          <div className="grid">
            <label>Summary<input value={summary} onChange={(event) => setSummary(event.target.value)} /></label>
            <label>Provenance<input required value={provenance} onChange={(event) => setProvenance(event.target.value)} /></label>
          </div>
          <button disabled={!canWrite} type="submit">Store revision</button>
        </form>
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>
      <section className="table-list">
        {loading ? <LoadingState label="Loading durable memory…" /> : records.length === 0 ? <EmptyState title="No durable memory is available" why="Store an explicit, sourced tenant fact to make it available to governed context." /> : records.map((record) => (
          <article className="panel" key={record.id}>
            <div className="panel-heading"><h3>{record.key}</h3><span>v{record.version} · {record.scope_type}</span></div>
            <p className="screen-note">{record.summary || "No summary"} · {record.provenance}</p>
            <pre>{JSON.stringify(record.value, null, 2)}</pre>
            <button disabled={!canWrite} type="button" onClick={() => void pin(record)}>{record.pinned ? "Unpin" : "Pin"}</button>
          </article>
        ))}
      </section>
    </div>
  );
}

function SkillsPanel({ canWrite }: { canWrite: boolean }) {
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [actions, setActions] = useState<SmartActionOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [instructions, setInstructions] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [schema, setSchema] = useState('{"type":"object","properties":{}}');
  const [testInput, setTestInput] = useState("{}");
  const [testOutput, setTestOutput] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [skillRows, actionRows] = await Promise.all([
        apiFetch<SkillRecord[]>("/packs/agent-platform/skills"),
        apiFetch<SmartActionOption[]>("/smart-actions")
      ]);
      setSkills(skillRows);
      setActions(actionRows);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load skills.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await apiFetch<SkillRecord>("/packs/agent-platform/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          slug,
          description: "",
          instructions,
          allowed_tools: tools,
          input_schema: parseJsonObject(schema, "Input schema"),
          resources: []
        })
      });
      setMessage("Skill created.");
      setName("");
      setSlug("");
      setInstructions("");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create skill.");
    }
  }

  async function runTest(skill: SkillRecord) {
    try {
      const result = await apiFetch<{ output: Record<string, unknown> }>(`/packs/agent-platform/skills/${skill.id}/tests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_input: parseJsonObject(testInput, "Test input"), memory: {} })
      });
      setTestOutput(result.output);
      setMessage("Validation completed without executing tools.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to test skill.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h3>Versioned skills</h3><span>{skills.length} active</span></div>
        <form className="draft-form" onSubmit={create}>
          <div className="grid">
            <label>Name<input required value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>Slug<input required value={slug} onChange={(event) => setSlug(event.target.value)} /></label>
          </div>
          <label>Instructions<textarea required rows={5} value={instructions} onChange={(event) => setInstructions(event.target.value)} placeholder="Use {{input.ticket_id}} placeholders." /></label>
          <fieldset>
            <legend>Allowed Smart Actions</legend>
            {actions.length === 0 ? <p className="screen-note">No Smart Actions are available in the current catalog.</p> : actions.map((action) => (
              <label key={action.action_id}>
                <input
                  type="checkbox"
                  checked={tools.includes(action.action_id)}
                  onChange={() => setTools((current) => current.includes(action.action_id) ? current.filter((id) => id !== action.action_id) : [...current, action.action_id])}
                />
                {action.title} ({action.action_id}) · {action.risk_level}{action.requires_approval ? " · approval required" : ""}
              </label>
            ))}
          </fieldset>
          <label>Input schema<textarea rows={4} value={schema} onChange={(event) => setSchema(event.target.value)} /></label>
          <button disabled={!canWrite} type="submit">Create skill</button>
        </form>
        <label>Validation input<textarea rows={3} value={testInput} onChange={(event) => setTestInput(event.target.value)} /></label>
        {testOutput ? <pre>{JSON.stringify(testOutput, null, 2)}</pre> : null}
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>
      <section className="table-list">
        {loading ? <LoadingState label="Loading governed skills…" /> : skills.length === 0 ? <EmptyState title="No governed skills are available" why="Create a versioned skill after selecting the Smart Actions it may use." /> : skills.map((skill) => (
          <article className="panel" key={skill.id}>
            <div className="panel-heading"><h3>{skill.name}</h3><span>v{skill.current_version}</span></div>
            <p className="screen-note">{skill.revision.allowed_tools.join(", ") || "No tools"}</p>
            <pre>{skill.revision.instructions}</pre>
            <button disabled={!canWrite} type="button" onClick={() => void runTest(skill)}>Validate safely</button>
          </article>
        ))}
      </section>
    </div>
  );
}

function IterationsPanel({ canWrite }: { canWrite: boolean }) {
  const [sessions, setSessions] = useState<IterationSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [sourceType, setSourceType] = useState<"agent" | "skill">("agent");
  const [sourceId, setSourceId] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [steps, setSteps] = useState("");
  const [finishReason, setFinishReason] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [sessionRows, agentRows, skillRows] = await Promise.all([
        apiFetch<IterationSession[]>("/packs/agent-platform/iterations"),
        apiFetch<AgentDefinition[]>("/agents"),
        apiFetch<SkillRecord[]>("/packs/agent-platform/skills")
      ]);
      setSessions(sessionRows);
      setAgents(agentRows);
      setSkills(skillRows);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load iteration sessions.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const sourceOptions = useMemo(() => sourceType === "agent"
    ? agents.map((agent) => ({ id: agent.id, name: agent.name }))
    : skills.map((skill) => ({ id: skill.id, name: skill.name })), [agents, skills, sourceType]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      let parsedSteps: unknown = undefined;
      if (sourceType === "skill") {
        parsedSteps = JSON.parse(steps);
        if (!Array.isArray(parsedSteps)) throw new Error("Steps must be a JSON array.");
      }
      await apiFetch<IterationSession>("/packs/agent-platform/iterations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_type: sourceType,
          source_id: sourceId,
          entity_id: ticketId,
          instruction,
          steps: parsedSteps
        })
      });
      setMessage("Iteration session created. No step has run yet.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create iteration session.");
    }
  }

  async function control(session: IterationSession, action: "continue" | "restart" | "finish") {
    try {
      await apiFetch<IterationSession>(`/packs/agent-platform/iterations/${session.id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action === "finish" ? { reason: finishReason.trim() } : {})
      });
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to update iteration session.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h3>Step iteration</h3><span>{sessions.length} sessions</span></div>
        <p className="screen-note">Each Continue action processes at most one existing Smart Action. Approval-required steps remain pending in the standard approval queue.</p>
        <form className="draft-form" onSubmit={create}>
          <div className="grid">
            <label>Source type<select value={sourceType} onChange={(event) => { setSourceType(event.target.value as "agent" | "skill"); setSourceId(""); }}><option value="agent">Agent</option><option value="skill">Skill</option></select></label>
            <label>Source<select required value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Choose</option>{sourceOptions.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>
            <label>Ticket ID<input required value={ticketId} onChange={(event) => setTicketId(event.target.value)} /></label>
          </div>
          <label>Session instruction<input required value={instruction} onChange={(event) => setInstruction(event.target.value)} /></label>
          {sourceType === "skill" ? <label>Bounded steps JSON<textarea required rows={4} value={steps} onChange={(event) => setSteps(event.target.value)} placeholder='[{"tool_id":"action-id","payload":{}}]' /></label> : null}
          <button disabled={!canWrite} type="submit">Create paused session</button>
        </form>
        <label>Finish reason (required before finishing)<input value={finishReason} onChange={(event) => setFinishReason(event.target.value)} /></label>
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>
      <section className="table-list">
        {loading ? <LoadingState label="Loading iteration sessions…" /> : sessions.length === 0 ? <EmptyState title="No iteration sessions are available" why="Create a paused session from an enabled agent or skill to review one governed step at a time." /> : sessions.map((session) => {
          const terminal = ["completed", "failed", "rejected", "cancelled"].includes(session.status);
          return <article className="panel" key={session.id}>
            <div className="panel-heading"><h3>{session.source_type}: {session.source_id}</h3><span>{session.status}</span></div>
            <p className="screen-note">Ticket {session.entity_id} · Step {session.current_step + 1}/{session.steps.length} · Approval {session.approval_id || "none"}</p>
            <p className="screen-note">Latest: {session.events.at(-1)?.event_type || "created"}</p>
            <div className="template-actions">
              <button disabled={!canWrite || terminal} type="button" onClick={() => void control(session, "continue")}>{session.status === "pending_approval" ? "Check approval" : "Continue one step"}</button>
              <button disabled={!canWrite || session.status === "pending_approval"} type="button" onClick={() => void control(session, "restart")}>Restart</button>
              <button disabled={!canWrite || !finishReason.trim() || terminal || session.status === "pending_approval"} type="button" onClick={() => void control(session, "finish")}>Finish</button>
            </div>
          </article>;
        })}
      </section>
    </div>
  );
}

function TechniciansPanel({ canWrite, isAdmin }: { canWrite: boolean; isAdmin: boolean }) {
  const [profiles, setProfiles] = useState<TechnicianProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [technicianId, setTechnicianId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [timezone, setTimezone] = useState("");
  const [workingHours, setWorkingHours] = useState("{}");
  const [expertise, setExpertise] = useState("");
  const [clientFamiliarity, setClientFamiliarity] = useState("");
  const [capacity, setCapacity] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [ticketId, setTicketId] = useState("");
  const [requiredExpertise, setRequiredExpertise] = useState("");
  const [recommendation, setRecommendation] = useState<TechnicianRecommendation | null>(null);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setProfiles(await apiFetch<TechnicianProfile[]>("/packs/agent-platform/technicians"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load technicians.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await apiFetch<TechnicianProfile>(`/packs/agent-platform/technicians/${technicianId}`, {
        method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            display_name: displayName,
            timezone,
            working_hours: parseJsonObject(workingHours, "Working hours"),
            expertise: splitValues(expertise),
            client_familiarity: Number(clientFamiliarity),
            capacity: Number(capacity),
            enabled
        })
      });
      setMessage("Technician profile saved.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save technician profile.");
    }
  }

  async function recommend() {
    try {
      const result = await apiFetch<TechnicianRecommendation>("/packs/agent-platform/technicians/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket_id: ticketId, required_expertise: splitValues(requiredExpertise) })
      });
      setRecommendation(result);
      setMessage("Recommendation calculated without changing ticket assignment.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to rank technicians.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h3>Technician intelligence</h3><span>{profiles.length} enabled</span></div>
        <form className="draft-form" onSubmit={save}>
          <div className="grid">
            <label>Technician ID<input required value={technicianId} onChange={(event) => setTechnicianId(event.target.value)} /></label>
            <label>Display name<input required value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
            <label>Timezone<input required value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label>
            <label>Expertise<input value={expertise} onChange={(event) => setExpertise(event.target.value)} placeholder="MFA, Entra, networking" /></label>
            <label>Client familiarity (0–5)<input required type="number" min="0" max="5" value={clientFamiliarity} onChange={(event) => setClientFamiliarity(event.target.value)} /></label>
            <label>Capacity (1–100)<input required type="number" min="1" max="100" value={capacity} onChange={(event) => setCapacity(event.target.value)} /></label>
          </div>
          <label>Working hours JSON<textarea required rows={3} value={workingHours} onChange={(event) => setWorkingHours(event.target.value)} /></label>
          <label><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> Profile enabled</label>
          <button disabled={!canWrite || !isAdmin} type="submit">Save profile</button>
        </form>
        <div className="grid">
          <label>Ticket ID<input value={ticketId} onChange={(event) => setTicketId(event.target.value)} /></label>
          <label>Required expertise<input value={requiredExpertise} onChange={(event) => setRequiredExpertise(event.target.value)} /></label>
        </div>
        <button disabled={!canWrite || !ticketId} type="button" onClick={() => void recommend()}>Rank technicians</button>
        {recommendation?.recommendation ? <div className="notice"><strong>{recommendation.recommendation.display_name}</strong> · score {recommendation.recommendation.score}<br />{recommendation.recommendation.reasons.join(" · ")}</div> : null}
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>
      <section className="table-list">
        {loading ? <LoadingState label="Loading technician profiles…" /> : profiles.length === 0 ? <EmptyState title="No technician profiles are available" why="An administrator can add a client-scoped profile before ranking workload." /> : profiles.map((profile) => <article className="panel" key={profile.technician_id}><div className="panel-heading"><h3>{profile.display_name}</h3><span>{profile.enabled ? "enabled" : "disabled"}</span></div><p className="screen-note">{profile.expertise.join(", ") || "No expertise labels"}</p><p className="screen-note">Capacity {profile.capacity} · Open tickets {profile.workload?.open_tickets ?? "unknown"}</p></article>)}
      </section>
    </div>
  );
}

function AttachmentsPanel({ canWrite, maxBytes }: { canWrite: boolean; maxBytes?: number }) {
  const [ticketId, setTicketId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [attachments, setAttachments] = useState<TicketAttachment[]>([]);
  const [analyses, setAnalyses] = useState<AttachmentAnalysis[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    if (!ticketId) return;
    setLoading(true);
    try {
      const [attachmentRows, analysisRows] = await Promise.all([
        apiFetch<TicketAttachment[]>(`/packs/agent-platform/tickets/${ticketId}/attachments`),
        apiFetch<AttachmentAnalysis[]>(`/packs/agent-platform/tickets/${ticketId}/attachments/analyses`)
      ]);
      setAttachments(attachmentRows);
      setAnalyses(analysisRows);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load attachments.");
    } finally {
      setLoading(false);
    }
  }, [ticketId]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    try {
      if (maxBytes === undefined) throw new Error("Upload limits are still loading. Try again in a moment.");
      if (file.size > maxBytes) throw new Error(`Image must be no larger than ${maxBytes} bytes.`);
      await apiFetch<TicketAttachment>(`/packs/agent-platform/tickets/${ticketId}/attachments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, media_type: file.type, content_base64: await fileToBase64(file) })
      });
      setMessage("Image stored privately. Raw bytes are not returned through the API.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to upload attachment.");
    }
  }

  async function analyze(attachment: TicketAttachment) {
    try {
      const result = await apiFetch<AttachmentAnalysis>(`/packs/agent-platform/tickets/${ticketId}/attachments/${attachment.id}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: "Summarize visible diagnostic evidence and limitations." })
      });
      setMessage(result.status === "ready" ? "Image evidence analyzed." : result.error_detail || `Analysis ${result.status}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to analyze attachment.");
    }
  }

  const latest = useMemo(() => {
    const map = new Map<string, AttachmentAnalysis>();
    analyses.forEach((analysis) => { if (!map.has(analysis.attachment_id)) map.set(analysis.attachment_id, analysis); });
    return map;
  }, [analyses]);

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><h3>Ticket image context</h3><span>{attachments.length} images</span></div>
        <form className="draft-form" onSubmit={upload}>
          <div className="grid">
            <label>Ticket ID<input required value={ticketId} onChange={(event) => setTicketId(event.target.value)} /></label>
            <label>PNG, JPEG, or WebP<input required accept="image/png,image/jpeg,image/webp" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
          </div>
          <div className="template-actions"><button type="button" disabled={!ticketId || loading} onClick={() => void refresh()}>Load</button><button type="submit" disabled={!canWrite || !file || maxBytes === undefined}>Store image</button></div>
        </form>
        {message ? <div className="notice" role="status">{message}</div> : null}
      </section>
      <section className="table-list">
        {loading ? <LoadingState label="Loading ticket images…" /> : attachments.length === 0 ? <EmptyState title="No ticket images are loaded" why="Enter a ticket ID and choose Load, or store a supported image for the selected ticket." /> : attachments.map((attachment) => {
          const analysis = latest.get(attachment.id);
          return <article className="panel" key={attachment.id}><div className="panel-heading"><h3>{attachment.filename}</h3><span>{attachment.byte_size} bytes</span></div><p className="screen-note">SHA-256 {attachment.sha256}</p>{analysis ? <pre>{JSON.stringify(analysis.status === "ready" ? analysis.result : { status: analysis.status, detail: analysis.error_detail }, null, 2)}</pre> : null}<button disabled={!canWrite} type="button" onClick={() => void analyze(attachment)}>Analyze visible evidence</button></article>;
        })}
      </section>
    </div>
  );
}

export function AgentPlatform() {
  const { canWrite, role, clients = [], selectedClientId = "", liveWritesReady = false, writeHealthResolved = false } = useDashboard();
  const [tab, setTab] = useState<PlatformTab>("memory");
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiFetch<PlatformStatus>("/packs/agent-platform/status")
      .then(setStatus)
      .catch((error: unknown) => setMessage(error instanceof Error ? error.message : "Unable to load agent platform status."));
  }, []);

  return (
    <div className="screen-stack">
      <StatusSummary
        status={status}
        selectedClientId={selectedClientId}
        clientName={clients.find((client) => client.client_id === selectedClientId)?.name}
        liveWritesReady={liveWritesReady}
        writeHealthResolved={writeHealthResolved}
      />
      {!selectedClientId ? <div className="notice" role="alert">Choose a client in the workspace scope selector before loading or changing agent-platform data.</div> : null}
      <section className="panel">
        <div className="template-actions" role="tablist" aria-label="Agent platform capabilities">
          {(["memory", "skills", "iterations", "technicians", "attachments"] as PlatformTab[]).map((item) => (
            <button key={item} type="button" role="tab" aria-selected={tab === item} onClick={() => setTab(item)}>{item[0].toUpperCase() + item.slice(1)}</button>
          ))}
        </div>
        {message ? <div className="notice danger" role="alert">{message}</div> : null}
      </section>
      {selectedClientId ? (
        <>
          {tab === "memory" ? <MemoryPanel key={selectedClientId} canWrite={canWrite} /> : null}
          {tab === "skills" ? <SkillsPanel key={selectedClientId} canWrite={canWrite} /> : null}
          {tab === "iterations" ? <IterationsPanel key={selectedClientId} canWrite={canWrite} /> : null}
          {tab === "technicians" ? <TechniciansPanel key={selectedClientId} canWrite={canWrite} isAdmin={role === "admin"} /> : null}
          {tab === "attachments" ? <AttachmentsPanel key={selectedClientId} canWrite={canWrite} maxBytes={status?.attachment_max_bytes} /> : null}
        </>
      ) : (
        <EmptyState
          title="Choose a client to load Agent Platform data"
          why="Select one client in the workspace scope selector before viewing or changing governed data."
        />
      )}
    </div>
  );
}
