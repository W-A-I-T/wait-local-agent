import { useCallback, useEffect, useMemo, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { ApiRequestError, apiFetch } from "../api/client";
import { Link } from "react-router-dom";
import { StatusChip } from "../components/StatusChip";
import type {
  MspPlaybook,
  MspPlaybookEntry,
  MspPlaybookRevision,
  MspPlaybookRevisionDiff,
  MspPlaybookSubscription
} from "../api/types";

type JsonResult = Record<string, unknown>;

export const MSP_PLAYBOOK_ENTRY_PATCH_FIELDS = ["definition", "provenance", "enabled"] as const;

type PlaybookDraft = {
  name: string;
  trigger: string;
  description: string;
  riskLevel: string;
  steps: string;
  outputEvidence: string;
  provenance: string;
  enabled: boolean;
};

type RevisionSelection = {
  fromVersion: string;
  toVersion: string;
};

type RestoreRequest = {
  entryId: string;
  version: number;
};

type SubscriptionDraft = {
  inputMapping: string;
  enabled: boolean;
  eventType: string;
  playbookId: string;
};

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? String(value);
}

function draftFromEntry(entry: MspPlaybookEntry): PlaybookDraft {
  return {
    name: entry.definition.name,
    trigger: entry.definition.trigger,
    description: entry.definition.description,
    riskLevel: entry.definition.risk_level,
    steps: jsonText(entry.definition.steps),
    outputEvidence: jsonText(entry.definition.output_evidence),
    provenance: entry.provenance,
    enabled: entry.enabled
  };
}

function validationMessage(error: unknown): string {
  if (error instanceof ApiRequestError && error.status === 422) {
    const detail = error.technicalDetail.split(": ").at(-1)?.trim();
    if (detail) return `Validation error: ${detail}`;
  }
  return error instanceof Error ? error.message : "Unable to save playbook changes.";
}

function renderDiffValue(value: unknown): string {
  return typeof value === "string" ? value : jsonText(value);
}

export function Playbooks() {
  const { canWrite, clientId, selectedTicketId } = useDashboard();
  const [playbooks, setPlaybooks] = useState<MspPlaybook[]>([]);
  const [entries, setEntries] = useState<MspPlaybookEntry[]>([]);
  const [subscriptions, setSubscriptions] = useState<MspPlaybookSubscription[]>([]);
  const [revisions, setRevisions] = useState<Record<string, MspPlaybookRevision[]>>({});
  const [diffs, setDiffs] = useState<Record<string, MspPlaybookRevisionDiff>>({});
  const [revisionSelections, setRevisionSelections] = useState<Record<string, RevisionSelection>>({});
  const [previews, setPreviews] = useState<Record<string, JsonResult>>({});
  const [runs, setRuns] = useState<Record<string, JsonResult>>({});
  const [ticketIds, setTicketIds] = useState<Record<string, string>>({});
  const [payloads, setPayloads] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, PlaybookDraft>>({});
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [editErrors, setEditErrors] = useState<Record<string, string>>({});
  const [savingEntryId, setSavingEntryId] = useState<string | null>(null);
  const [confirmingRestore, setConfirmingRestore] = useState<RestoreRequest | null>(null);
  const [subscriptionDrafts, setSubscriptionDrafts] = useState<Record<string, SubscriptionDraft>>({});
  const [editingSubscriptionId, setEditingSubscriptionId] = useState<string | null>(null);
  const [subscriptionEditErrors, setSubscriptionEditErrors] = useState<Record<string, string>>({});
  const [savingSubscriptionId, setSavingSubscriptionId] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const entryBySourceId = useMemo(
    () => new Map(entries.map((entry) => [entry.source_playbook_id, entry])),
    [entries]
  );
  const playbookNameById = useMemo(() => {
    const names = new Map(playbooks.map((playbook) => [playbook.id, playbook.name]));
    entries.forEach((entry) => names.set(entry.id, entry.definition.name));
    return names;
  }, [entries, playbooks]);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      apiFetch<MspPlaybook[]>("/msp/playbooks"),
      apiFetch<MspPlaybookEntry[]>("/msp/playbook-entries"),
      apiFetch<MspPlaybookSubscription[]>("/msp/playbook-subscriptions")
    ]);
    const errors: string[] = [];
    const [playbookResult, entryResult, subscriptionResult] = results;
    if (playbookResult.status === "fulfilled") setPlaybooks(playbookResult.value);
    else errors.push("The playbook library is unavailable.");
    if (entryResult.status === "fulfilled") setEntries(entryResult.value);
    else errors.push("Published playbook status is unavailable.");
    if (subscriptionResult.status === "fulfilled") setSubscriptions(subscriptionResult.value);
    else errors.push("Playbook event subscriptions are unavailable.");
    if (errors.length) {
      setMessage(errors.join(" "));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function executionId(playbook: MspPlaybook): string {
    return entryBySourceId.get(playbook.id)?.id ?? playbook.id;
  }

  function requestBody(playbook: MspPlaybook): Record<string, unknown> | null {
    const rawPayload = payloads[playbook.id]?.trim() || "{}";
    let payload: unknown;
    try {
      payload = JSON.parse(rawPayload);
    } catch {
      setMessage(`${playbook.name}: input must be valid JSON.`);
      return null;
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      setMessage(`${playbook.name}: input must be a JSON object.`);
      return null;
    }
    return {
      ticket_id: ticketIds[playbook.id]?.trim() || selectedTicketId || undefined,
      client_id: clientId || undefined,
      payload
    };
  }

  async function preview(playbook: MspPlaybook) {
    if (!canWrite) return;
    const body = requestBody(playbook);
    if (!body) return;
    try {
      const result = await apiFetch<JsonResult>(`/msp/playbooks/${encodeURIComponent(executionId(playbook))}/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      setPreviews((current) => ({ ...current, [playbook.id]: result }));
      setMessage(`Preview ready for ${playbook.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to preview this playbook.");
    }
  }

  async function run(playbook: MspPlaybook) {
    if (!canWrite) return;
    const body = requestBody(playbook);
    if (!body) return;
    try {
      const result = await apiFetch<JsonResult>(`/msp/playbooks/${encodeURIComponent(executionId(playbook))}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      setRuns((current) => ({ ...current, [playbook.id]: result }));
      setMessage(`Started ${playbook.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to run this playbook.");
    }
  }

  async function publish(playbook: MspPlaybook) {
    if (!canWrite) return;
    try {
      await apiFetch<MspPlaybookEntry>("/msp/playbook-entries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_playbook_id: playbook.id,
          provenance: "Published from the Playbooks dashboard.",
          enabled: true,
          client_id: clientId || undefined
        })
      });
      setMessage(`Published ${playbook.name}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to publish this playbook.");
    }
  }

  async function toggleEntry(entry: MspPlaybookEntry) {
    if (!canWrite) return;
    const action = entry.enabled ? "disable" : "enable";
    try {
      const updated = await apiFetch<MspPlaybookEntry>(
        `/msp/playbook-entries/${encodeURIComponent(entry.id)}/${action}`,
        { method: "POST" }
      );
      setEntries((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage(`${updated.definition.name} is now ${updated.enabled ? "enabled" : "disabled"}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to change playbook availability.");
    }
  }

  function editEntry(entry: MspPlaybookEntry) {
    if (!canWrite) return;
    setDrafts((current) => ({ ...current, [entry.id]: draftFromEntry(entry) }));
    setEditErrors((current) => ({ ...current, [entry.id]: "" }));
    setEditingEntryId(entry.id);
  }

  function updateDraft(entry: MspPlaybookEntry, changes: Partial<PlaybookDraft>) {
    setDrafts((current) => ({
      ...current,
      [entry.id]: { ...(current[entry.id] ?? draftFromEntry(entry)), ...changes }
    }));
    setEditErrors((current) => ({ ...current, [entry.id]: "" }));
  }

  async function saveEntry(entry: MspPlaybookEntry) {
    if (!canWrite) return;
    const draft = drafts[entry.id] ?? draftFromEntry(entry);
    let steps: unknown;
    let outputEvidence: unknown;
    try {
      steps = JSON.parse(draft.steps);
    } catch {
      setEditErrors((current) => ({ ...current, [entry.id]: "Validation error: steps must be valid JSON." }));
      return;
    }
    try {
      outputEvidence = JSON.parse(draft.outputEvidence);
    } catch {
      setEditErrors((current) => ({ ...current, [entry.id]: "Validation error: output evidence must be valid JSON." }));
      return;
    }
    if (!Array.isArray(steps)) {
      setEditErrors((current) => ({ ...current, [entry.id]: "Validation error: steps must be a JSON array." }));
      return;
    }
    if (!Array.isArray(outputEvidence)) {
      setEditErrors((current) => ({ ...current, [entry.id]: "Validation error: output evidence must be a JSON array." }));
      return;
    }
    if (!draft.provenance.trim()) {
      setEditErrors((current) => ({ ...current, [entry.id]: "Validation error: provenance cannot be empty." }));
      return;
    }

    setSavingEntryId(entry.id);
    setEditErrors((current) => ({ ...current, [entry.id]: "" }));
    try {
      const body = {
        definition: {
          name: draft.name.trim(),
          trigger: draft.trigger.trim(),
          description: draft.description.trim(),
          risk_level: draft.riskLevel,
          steps,
          output_evidence: outputEvidence,
          ...(entry.definition.local_fixture === undefined ? {} : { local_fixture: entry.definition.local_fixture })
        },
        provenance: draft.provenance.trim(),
        enabled: draft.enabled
      } satisfies Record<(typeof MSP_PLAYBOOK_ENTRY_PATCH_FIELDS)[number], unknown>;
      const updated = await apiFetch<MspPlaybookEntry>(`/msp/playbook-entries/${encodeURIComponent(entry.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      setEntries((current) => current.map((item) => item.id === updated.id ? updated : item));
      setEditingEntryId(null);
      setMessage(`Saved ${updated.definition.name} as version ${updated.version}.`);
      await refresh();
    } catch (error) {
      setEditErrors((current) => ({ ...current, [entry.id]: validationMessage(error) }));
    } finally {
      setSavingEntryId(null);
    }
  }

  async function showRevisions(entry: MspPlaybookEntry) {
    try {
      const rows = await apiFetch<MspPlaybookRevision[]>(
        `/msp/playbook-entries/${encodeURIComponent(entry.id)}/revisions`
      );
      setRevisions((current) => ({ ...current, [entry.id]: rows }));
      setRevisionSelections((current) => ({
        ...current,
        [entry.id]: { fromVersion: "", toVersion: "" }
      }));
      setDiffs((current) => {
        const next = { ...current };
        delete next[entry.id];
        return next;
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load playbook history.");
    }
  }

  async function compareRevisions(entry: MspPlaybookEntry) {
    const selection = revisionSelections[entry.id];
    if (!selection?.fromVersion || !selection.toVersion || selection.fromVersion === selection.toVersion) {
      return;
    }
    try {
      const diff = await apiFetch<MspPlaybookRevisionDiff>(
        `/msp/playbook-entries/${encodeURIComponent(entry.id)}/revisions/diff?from_version=${encodeURIComponent(selection.fromVersion)}&to_version=${encodeURIComponent(selection.toVersion)}`
      );
      setDiffs((current) => ({ ...current, [entry.id]: diff }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to compare playbook history.");
    }
  }

  async function restoreRevision(entry: MspPlaybookEntry, revision: MspPlaybookRevision) {
    if (!canWrite) return;
    setConfirmingRestore({ entryId: entry.id, version: revision.version });
  }

  async function confirmRestore(entry: MspPlaybookEntry, version: number) {
    if (!canWrite) return;
    setConfirmingRestore(null);
    try {
      const restored = await apiFetch<MspPlaybookEntry>(
        `/msp/playbook-entries/${encodeURIComponent(entry.id)}/revisions/${version}/restore`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      setEntries((current) => current.map((item) => item.id === restored.id ? restored : item));
      setMessage(`Restored ${restored.definition.name} as version ${restored.version}.`);
      setDrafts((current) => ({ ...current, [restored.id]: draftFromEntry(restored) }));
      await showRevisions(restored);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to restore playbook history.");
    }
  }

  async function toggleSubscription(subscription: MspPlaybookSubscription) {
    if (!canWrite) return;
    const action = subscription.enabled ? "disable" : "enable";
    try {
      const updated = await apiFetch<MspPlaybookSubscription>(
        `/msp/playbook-subscriptions/${encodeURIComponent(subscription.id)}/${action}`,
        { method: "POST" }
      );
      setSubscriptions((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage(`Event subscription is now ${updated.enabled ? "enabled" : "disabled"}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to change the event subscription.");
    }
  }

  async function editSubscription(subscription: MspPlaybookSubscription) {
    if (!canWrite) return;
    try {
      const current = await apiFetch<MspPlaybookSubscription>(`/msp/playbook-subscriptions/${encodeURIComponent(subscription.id)}`);
      setSubscriptionDrafts((drafts) => ({
        ...drafts,
        [subscription.id]: {
          inputMapping: jsonText(current.input_mapping),
          enabled: current.enabled,
          eventType: current.event_type,
          playbookId: current.playbook_id
        }
      }));
      setSubscriptionEditErrors((errors) => ({ ...errors, [subscription.id]: "" }));
      setEditingSubscriptionId(subscription.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load the event subscription.");
    }
  }

  async function saveSubscription(subscription: MspPlaybookSubscription) {
    if (!canWrite) return;
    const draft = subscriptionDrafts[subscription.id];
    if (!draft) return;
    let inputMapping: unknown;
    try {
      inputMapping = JSON.parse(draft.inputMapping);
    } catch {
      setSubscriptionEditErrors((errors) => ({ ...errors, [subscription.id]: "Input mapping must be valid JSON." }));
      return;
    }
    if (!inputMapping || typeof inputMapping !== "object" || Array.isArray(inputMapping)) {
      setSubscriptionEditErrors((errors) => ({ ...errors, [subscription.id]: "Input mapping must be a JSON object." }));
      return;
    }
    setSavingSubscriptionId(subscription.id);
    setSubscriptionEditErrors((errors) => ({ ...errors, [subscription.id]: "" }));
    try {
      const updated = await apiFetch<MspPlaybookSubscription>(`/msp/playbook-subscriptions/${encodeURIComponent(subscription.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input_mapping: inputMapping, enabled: draft.enabled })
      });
      setSubscriptions((current) => current.map((item) => item.id === updated.id ? updated : item));
      setEditingSubscriptionId(null);
      setMessage("Event subscription saved.");
    } catch (error) {
      setSubscriptionEditErrors((errors) => ({ ...errors, [subscription.id]: error instanceof Error ? error.message : "Unable to save the event subscription." }));
    } finally {
      setSavingSubscriptionId(null);
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>MSP Playbooks</h2>
          <span>{playbooks.length} library playbooks</span>
        </div>
        <p className="screen-note">
          Review bounded service workflows, publish a tenant copy, preview inputs, and start an approved run.
        </p>
        <p className="screen-note automation-cross-link">
          Workflows run single reviewed actions — <Link to="/workflows">see Run</Link>. Customize tenant copies in <Link to="/templates">My templates</Link>.
        </p>
        {message ? <div className="notice" role="status">{message}</div> : null}
        <div className="table-list">
          {playbooks.length === 0 ? <p>No playbooks are available.</p> : null}
          {playbooks.map((playbook) => {
            const entry = entryBySourceId.get(playbook.id);
            const definition = entry?.definition ?? playbook;
            const previewResult = previews[playbook.id];
            const runResult = runs[playbook.id];
            const requiredInputs = uniqueValues(definition.steps.flatMap((step) => step.required_inputs ?? []));
            const workflowSteps = uniqueValues(
              definition.steps.filter((step) => step.kind === "workflow").map((step) => step.name)
            );
            const draft = entry ? drafts[entry.id] : undefined;
            const selection = entry ? revisionSelections[entry.id] : undefined;
            const diff = entry ? diffs[entry.id] : undefined;
            return (
              <article className="table-row playbook-row" key={playbook.id}>
                <div>
                  <strong>{definition.name}</strong>
                  <span>{definition.description}</span>
                  <div className="status-chip-wrap">
                    <StatusChip status={entry ? "published" : "unpublished"} hint={entry ? `Version ${entry.version}` : "Publish a tenant copy to manage availability."} />
                    {entry ? <StatusChip status={entry.enabled ? "enabled" : "disabled"} /> : null}
                  </div>
                </div>
                <div>
                  <strong>Trigger</strong>
                  <span>{definition.trigger}</span>
                  <strong>Risk</strong>
                  <span><StatusChip status={definition.risk_level} /></span>
                </div>
                <div>
                  <strong>Requirements</strong>
                  <span>{requiredInputs.length ? `Inputs: ${requiredInputs.join(", ")}` : "No additional inputs"}</span>
                  <span>{workflowSteps.length ? `Steps: ${workflowSteps.join(", ")}` : "No workflow steps"}</span>
                  <span>Connector requirements are declared by the underlying steps.</span>
                  <span>Approval is confirmed in the preview response.</span>
                </div>
                <div>
                  <strong>Last run</strong>
                  <span>{runResult ? String(runResult.status ?? "Started") : "No run recorded in this view."}</span>
                </div>
                <div className="template-actions">
                  {entry ? (
                    <button type="button" disabled={!canWrite} onClick={() => void toggleEntry(entry)}>
                      {entry.enabled ? "Disable" : "Enable"}
                    </button>
                  ) : (
                    <button type="button" disabled={!canWrite} onClick={() => void publish(playbook)}>Publish</button>
                  )}
                  {entry ? <button type="button" disabled={!canWrite} onClick={() => editEntry(entry)}>Edit</button> : null}
                  <button type="button" disabled={!canWrite || Boolean(entry && !entry.enabled)} onClick={() => void preview(playbook)}>Preview</button>
                  <button type="button" disabled={!canWrite || Boolean(entry && !entry.enabled)} onClick={() => void run(playbook)}>Run</button>
                </div>
                {entry && editingEntryId === entry.id && draft ? (
                  <form className="playbook-edit-form" onSubmit={(event) => { event.preventDefault(); void saveEntry(entry); }}>
                    <div className="panel-heading">
                      <h3>Edit published playbook</h3>
                      <span>Changes create version {entry.version + 1}</span>
                    </div>
                    <div className="grid">
                      <label>
                        Name
                        <input value={draft.name} onChange={(event) => updateDraft(entry, { name: event.target.value })} />
                      </label>
                      <label>
                        Trigger
                        <input value={draft.trigger} onChange={(event) => updateDraft(entry, { trigger: event.target.value })} />
                      </label>
                      <label>
                        Risk level
                        <select value={draft.riskLevel} onChange={(event) => updateDraft(entry, { riskLevel: event.target.value })}>
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </label>
                      <label>
                        Provenance
                        <input value={draft.provenance} onChange={(event) => updateDraft(entry, { provenance: event.target.value })} />
                      </label>
                    </div>
                    <label>
                      Description
                      <textarea rows={3} value={draft.description} onChange={(event) => updateDraft(entry, { description: event.target.value })} />
                    </label>
                    <div className="grid">
                      <label>
                        Steps JSON
                        <textarea rows={7} value={draft.steps} onChange={(event) => updateDraft(entry, { steps: event.target.value })} spellCheck={false} />
                      </label>
                      <label>
                        Output evidence JSON
                        <textarea rows={7} value={draft.outputEvidence} onChange={(event) => updateDraft(entry, { outputEvidence: event.target.value })} spellCheck={false} />
                      </label>
                    </div>
                    <label className="checkbox-label">
                      <input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft(entry, { enabled: event.target.checked })} />
                      Enabled
                    </label>
                    {editErrors[entry.id] ? <p className="inline-error" role="alert">{editErrors[entry.id]}</p> : null}
                    <div className="template-actions">
                      <button type="submit" disabled={!canWrite || savingEntryId === entry.id}>{savingEntryId === entry.id ? "Saving…" : "Save changes"}</button>
                      <button type="button" disabled={savingEntryId === entry.id} onClick={() => setEditingEntryId(null)}>Cancel</button>
                    </div>
                  </form>
                ) : null}
                <div className="grid">
                  <label>
                    Ticket id (optional)
                    <input
                      aria-label={`Ticket id for ${playbook.name}`}
                      value={ticketIds[playbook.id] ?? ""}
                      onChange={(event) => setTicketIds((current) => ({ ...current, [playbook.id]: event.target.value }))}
                      placeholder={selectedTicketId || "TCK-1001"}
                    />
                  </label>
                  <label>
                    Input JSON
                    <textarea
                      aria-label={`Input JSON for ${playbook.name}`}
                      rows={2}
                      value={payloads[playbook.id] ?? "{}"}
                      onChange={(event) => setPayloads((current) => ({ ...current, [playbook.id]: event.target.value }))}
                    />
                  </label>
                </div>
                {previewResult ? <pre className="technical-details">Preview: {jsonText(previewResult)}</pre> : null}
                {runResult ? <pre className="technical-details">Run: {jsonText(runResult)}</pre> : null}
                {entry ? (
                  <details className="playbook-revisions-drawer">
                    <summary onClick={() => { if (!revisions[entry.id]) void showRevisions(entry); }}>History and recovery</summary>
                    {revisions[entry.id] ? (
                      <div className="event-list" aria-label={`Revisions for ${definition.name}`}>
                        <div className="grid revision-selector">
                          <label>
                            From revision
                            <select
                              aria-label={`From revision for ${definition.name}`}
                              value={selection?.fromVersion ?? ""}
                              onChange={(event) => setRevisionSelections((current) => ({
                                ...current,
                                [entry.id]: { fromVersion: event.target.value, toVersion: selection?.toVersion ?? "" }
                              }))}
                            >
                              <option value="">Choose a version</option>
                              {revisions[entry.id].map((revision) => <option key={revision.version} value={revision.version}>Version {revision.version}</option>)}
                            </select>
                          </label>
                          <label>
                            To revision
                            <select
                              aria-label={`To revision for ${definition.name}`}
                              value={selection?.toVersion ?? ""}
                              onChange={(event) => setRevisionSelections((current) => ({
                                ...current,
                                [entry.id]: { fromVersion: selection?.fromVersion ?? "", toVersion: event.target.value }
                              }))}
                            >
                              <option value="">Choose a version</option>
                              {revisions[entry.id].map((revision) => <option key={revision.version} value={revision.version}>Version {revision.version}</option>)}
                            </select>
                          </label>
                          <button
                            type="button"
                            disabled={!selection?.fromVersion || !selection.toVersion || selection.fromVersion === selection.toVersion}
                            onClick={() => void compareRevisions(entry)}
                          >
                            Compare revisions
                          </button>
                        </div>
                        {revisions[entry.id].map((revision) => (
                          <article className="event-row" key={revision.id}>
                            <span>Version {revision.version}</span>
                            <span>{revision.created_at}</span>
                            <button type="button" disabled={!canWrite || revision.version === entry.version} onClick={() => void restoreRevision(entry, revision)}>Restore</button>
                          </article>
                        ))}
                        {confirmingRestore?.entryId === entry.id ? (
                          <div className="notice confirm-panel" role="alertdialog" aria-label="Confirm playbook restore">
                            <p>Restore version {confirmingRestore.version} of {definition.name}? This creates a new current version.</p>
                            <div className="template-actions">
                              <button type="button" onClick={() => void confirmRestore(entry, confirmingRestore.version)}>Confirm restore</button>
                              <button type="button" className="icon-button" onClick={() => setConfirmingRestore(null)}>Cancel</button>
                            </div>
                          </div>
                        ) : null}
                        {diff ? <div className="playbook-diff" aria-label={`Revision diff for ${definition.name}`}>
                          <strong>Changes: v{diff.from_version} → v{diff.to_version}</strong>
                          {diff.changed_fields.length === 0 ? <p>No changes.</p> : <ul>{diff.changed_fields.map((field) => <li key={field}><code>{field}</code><div><span>Before</span><pre>{renderDiffValue(diff.from[field])}</pre></div><div><span>After</span><pre>{renderDiffValue(diff.to[field])}</pre></div></li>)}</ul>}
                        </div> : null}
                      </div>
                    ) : <p className="screen-note">Loading history.</p>}
                  </details>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Event subscriptions</h2>
          <span>{subscriptions.length}</span>
        </div>
        <p className="screen-note">Event subscriptions use the playbook trigger and stay scoped to the current tenant.</p>
        {subscriptions.length === 0 ? <p>No event subscriptions are configured.</p> : null}
        <div className="event-list">
          {subscriptions.map((subscription) => (
            <article className="event-row" key={subscription.id}>
              <div>
                <strong>{playbookNameById.get(subscription.playbook_id) ?? subscription.playbook_id}</strong>
                <span>{subscription.event_type}</span>
              </div>
              <StatusChip status={subscription.enabled ? "enabled" : "disabled"} />
              <button type="button" disabled={!canWrite} onClick={() => void editSubscription(subscription)}>Edit</button>
              <button type="button" disabled={!canWrite} onClick={() => void toggleSubscription(subscription)}>
                {subscription.enabled ? "Disable" : "Enable"}
              </button>
              {editingSubscriptionId === subscription.id && subscriptionDrafts[subscription.id] ? (
                <form className="playbook-edit-form" onSubmit={(event) => { event.preventDefault(); void saveSubscription(subscription); }}>
                  <div className="grid">
                    <label>
                      Event type
                      <input value={subscriptionDrafts[subscription.id].eventType} readOnly />
                    </label>
                    <label>
                      Playbook binding
                      <input value={playbookNameById.get(subscriptionDrafts[subscription.id].playbookId) ?? subscriptionDrafts[subscription.id].playbookId} readOnly />
                    </label>
                  </div>
                  <label>
                    Input mapping JSON
                    <textarea rows={5} value={subscriptionDrafts[subscription.id].inputMapping} onChange={(event) => setSubscriptionDrafts((drafts) => ({
                      ...drafts,
                      [subscription.id]: { ...drafts[subscription.id], inputMapping: event.target.value }
                    }))} spellCheck={false} />
                  </label>
                  <label className="checkbox-label">
                    <input type="checkbox" checked={subscriptionDrafts[subscription.id].enabled} onChange={(event) => setSubscriptionDrafts((drafts) => ({
                      ...drafts,
                      [subscription.id]: { ...drafts[subscription.id], enabled: event.target.checked }
                    }))} />
                    Enabled
                  </label>
                  {subscriptionEditErrors[subscription.id] ? <p className="inline-error" role="alert">{subscriptionEditErrors[subscription.id]}</p> : null}
                  <div className="template-actions">
                    <button type="submit" disabled={savingSubscriptionId === subscription.id}>{savingSubscriptionId === subscription.id ? "Saving…" : "Save changes"}</button>
                    <button type="button" className="icon-button" disabled={savingSubscriptionId === subscription.id} onClick={() => setEditingSubscriptionId(null)}>Cancel</button>
                  </div>
                </form>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
