import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import type { TemplateGalleryEntry, TemplateGalleryRevision, WorkflowTemplate } from "../api/types";

type GalleryDraft = {
  name: string;
  description: string;
  instructions: string;
};

export function Templates() {
  const { canWrite } = useDashboard();
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [entries, setEntries] = useState<TemplateGalleryEntry[]>([]);
  const [drafts, setDrafts] = useState<Record<string, GalleryDraft>>({});
  const [ticketIds, setTicketIds] = useState<Record<string, string>>({});
  const [revisions, setRevisions] = useState<Record<string, TemplateGalleryRevision[]>>({});
  const [sourceTemplateId, setSourceTemplateId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [provenance, setProvenance] = useState("Reviewed by local operator");
  const [instructions, setInstructions] = useState("");
  const [clientId, setClientId] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [coreRows, galleryRows] = await Promise.all([
        apiFetch<WorkflowTemplate[]>("/workflows/templates"),
        apiFetch<TemplateGalleryEntry[]>("/workflow-templates/gallery")
      ]);
      setTemplates(coreRows);
      setEntries(galleryRows);
      setDrafts(Object.fromEntries(galleryRows.map((entry) => [entry.id, {
        name: entry.name,
        description: entry.description,
        instructions: entry.instructions
      }])));
      if (!sourceTemplateId && coreRows[0]) {
        setSourceTemplateId(coreRows[0].id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load template gallery.");
    }
  }, [sourceTemplateId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sourceTemplateId || !provenance.trim()) {
      setMessage("Choose a reviewed template and provide its source note.");
      return;
    }
    try {
      await apiFetch<TemplateGalleryEntry>("/workflow-templates/gallery", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_template_id: sourceTemplateId,
          provenance,
          display_name: displayName || undefined,
          instructions,
          client_id: clientId || undefined
        })
      });
      setMessage("Local template created.");
      setDisplayName("");
      setInstructions("");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create local template.");
    }
  }

  async function saveEntry(entry: TemplateGalleryEntry) {
    const draft = drafts[entry.id];
    if (!draft) return;
    try {
      const updated = await apiFetch<TemplateGalleryEntry>(`/workflow-templates/gallery/${encodeURIComponent(entry.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft)
      });
      setEntries((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage(`Saved ${updated.name} as version ${updated.version}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save local template.");
    }
  }

  async function setEnabled(entry: TemplateGalleryEntry, enabled: boolean) {
    try {
      const updated = await apiFetch<TemplateGalleryEntry>(`/workflow-templates/gallery/${encodeURIComponent(entry.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled })
      });
      setEntries((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage(`${updated.name} is now ${updated.enabled ? "enabled" : "disabled"}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to change template availability.");
    }
  }

  async function runEntry(entry: TemplateGalleryEntry) {
    const ticketId = ticketIds[entry.id]?.trim();
    if (!ticketId) {
      setMessage("Provide a ticket id before running a template.");
      return;
    }
    try {
      await apiFetch(`/workflow-templates/gallery/${encodeURIComponent(entry.id)}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket_id: ticketId })
      });
      setMessage(`Started ${entry.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to run local template.");
    }
  }

  async function showRevisions(entry: TemplateGalleryEntry) {
    try {
      const rows = await apiFetch<TemplateGalleryRevision[]>(`/workflow-templates/gallery/${encodeURIComponent(entry.id)}/revisions`);
      setRevisions((current) => ({ ...current, [entry.id]: rows }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load template history.");
    }
  }

  async function restoreRevision(entry: TemplateGalleryEntry, version: number) {
    try {
      const restored = await apiFetch<TemplateGalleryEntry>(
        `/workflow-templates/gallery/${encodeURIComponent(entry.id)}/revisions/${version}/restore`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      setEntries((current) => current.map((item) => item.id === restored.id ? restored : item));
      setDrafts((current) => ({ ...current, [restored.id]: {
        name: restored.name,
        description: restored.description,
        instructions: restored.instructions
      }}));
      setMessage(`Restored ${restored.name} as version ${restored.version}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to restore template history.");
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>Template Gallery</h2>
          <span>{entries.length} local templates</span>
        </div>
        <p className="screen-note">Create tenant-scoped copies of reviewed templates, edit their operator notes, and keep a recoverable local history.</p>
        <form className="draft-form" onSubmit={createEntry}>
          <div className="grid">
            <label>Reviewed template<select value={sourceTemplateId} onChange={(event) => setSourceTemplateId(event.target.value)}>
              <option value="">Choose template</option>
              {templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
            </select></label>
            <label>Display name<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Acme triage" /></label>
            <label>Source note<input value={provenance} onChange={(event) => setProvenance(event.target.value)} /></label>
            <label>Client id (optional)<input value={clientId} onChange={(event) => setClientId(event.target.value)} /></label>
          </div>
          <label>Operator instructions<textarea rows={3} value={instructions} onChange={(event) => setInstructions(event.target.value)} /></label>
          <button type="submit" disabled={!canWrite || !sourceTemplateId}>Create local template</button>
        </form>
        {message ? <div className="notice">{message}</div> : null}
      </section>

      <section className="template-gallery-grid">
        {entries.length === 0 ? <p className="panel">No local templates yet.</p> : null}
        {entries.map((entry) => {
          const draft = drafts[entry.id] ?? { name: entry.name, description: entry.description, instructions: entry.instructions };
          const entryRevisions = revisions[entry.id] ?? [];
          return (
            <article className="panel template-card" key={entry.id}>
              <div className="panel-heading"><h3>{entry.name}</h3><span>Version {entry.version}</span></div>
              <p className="screen-note">Source: {entry.source_template_id} · {entry.enabled ? "enabled" : "disabled"}</p>
              <label>Name<input value={draft.name} onChange={(event) => setDrafts((current) => ({ ...current, [entry.id]: { ...draft, name: event.target.value } }))} /></label>
              <label>Description<textarea rows={2} value={draft.description} onChange={(event) => setDrafts((current) => ({ ...current, [entry.id]: { ...draft, description: event.target.value } }))} /></label>
              <label>Instructions<textarea rows={2} value={draft.instructions} onChange={(event) => setDrafts((current) => ({ ...current, [entry.id]: { ...draft, instructions: event.target.value } }))} /></label>
              <div className="template-actions">
                <button type="button" disabled={!canWrite} onClick={() => void saveEntry(entry)}>Save changes</button>
                <button type="button" disabled={!canWrite} onClick={() => void setEnabled(entry, !entry.enabled)}>{entry.enabled ? "Disable" : "Enable"}</button>
                <button type="button" onClick={() => void showRevisions(entry)}>History</button>
              </div>
              <div className="template-run-row">
                <input aria-label={`Ticket for ${entry.name}`} value={ticketIds[entry.id] ?? ""} onChange={(event) => setTicketIds((current) => ({ ...current, [entry.id]: event.target.value }))} placeholder="Ticket id" />
                <button type="button" disabled={!canWrite || !entry.enabled} onClick={() => void runEntry(entry)}>Run</button>
              </div>
              {entryRevisions.length ? <div className="template-history"><strong>History</strong>{entryRevisions.map((revision) => <button type="button" key={revision.version} disabled={!canWrite || revision.version === entry.version} onClick={() => void restoreRevision(entry, revision.version)}>Restore v{revision.version}</button>)}</div> : null}
            </article>
          );
        })}
      </section>
    </div>
  );
}
