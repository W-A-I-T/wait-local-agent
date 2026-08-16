import { useCallback, useEffect, useMemo, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { StatusChip } from "../components/StatusChip";
import type {
  MspPlaybook,
  MspPlaybookEntry,
  MspPlaybookRevision,
  MspPlaybookRevisionDiff,
  MspPlaybookSubscription
} from "../api/types";

type JsonResult = Record<string, unknown>;

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? String(value);
}

export function Playbooks() {
  const { canWrite, clientId, selectedTicketId } = useDashboard();
  const [playbooks, setPlaybooks] = useState<MspPlaybook[]>([]);
  const [entries, setEntries] = useState<MspPlaybookEntry[]>([]);
  const [subscriptions, setSubscriptions] = useState<MspPlaybookSubscription[]>([]);
  const [revisions, setRevisions] = useState<Record<string, MspPlaybookRevision[]>>({});
  const [diffs, setDiffs] = useState<Record<string, MspPlaybookRevisionDiff>>({});
  const [previews, setPreviews] = useState<Record<string, JsonResult>>({});
  const [runs, setRuns] = useState<Record<string, JsonResult>>({});
  const [ticketIds, setTicketIds] = useState<Record<string, string>>({});
  const [payloads, setPayloads] = useState<Record<string, string>>({});
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

  async function showRevisions(entry: MspPlaybookEntry) {
    try {
      const rows = await apiFetch<MspPlaybookRevision[]>(
        `/msp/playbook-entries/${encodeURIComponent(entry.id)}/revisions`
      );
      setRevisions((current) => ({ ...current, [entry.id]: rows }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load playbook history.");
    }
  }

  async function compareRevision(entry: MspPlaybookEntry, revision: MspPlaybookRevision) {
    try {
      const diff = await apiFetch<MspPlaybookRevisionDiff>(
        `/msp/playbook-entries/${encodeURIComponent(entry.id)}/revisions/diff?from_version=${revision.version}&to_version=${entry.version}`
      );
      setDiffs((current) => ({ ...current, [entry.id]: diff }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to compare playbook history.");
    }
  }

  async function restoreRevision(entry: MspPlaybookEntry, revision: MspPlaybookRevision) {
    if (!canWrite) return;
    try {
      const restored = await apiFetch<MspPlaybookEntry>(
        `/msp/playbook-entries/${encodeURIComponent(entry.id)}/revisions/${revision.version}/restore`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      setEntries((current) => current.map((item) => item.id === restored.id ? restored : item));
      setMessage(`Restored ${restored.definition.name} as version ${restored.version}.`);
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
        {message ? <div className="notice" role="status">{message}</div> : null}
        <div className="table-list">
          {playbooks.length === 0 ? <p>No playbooks are available.</p> : null}
          {playbooks.map((playbook) => {
            const entry = entryBySourceId.get(playbook.id);
            const previewResult = previews[playbook.id];
            const runResult = runs[playbook.id];
            const requiredInputs = uniqueValues(playbook.steps.flatMap((step) => step.required_inputs ?? []));
            const workflowSteps = uniqueValues(
              playbook.steps.filter((step) => step.kind === "workflow").map((step) => step.name)
            );
            return (
              <article className="table-row playbook-row" key={playbook.id}>
                <div>
                  <strong>{playbook.name}</strong>
                  <span>{playbook.description}</span>
                  <div className="status-chip-wrap">
                    <StatusChip status={entry ? "published" : "unpublished"} hint={entry ? `Version ${entry.version}` : "Publish a tenant copy to manage availability."} />
                    {entry ? <StatusChip status={entry.enabled ? "enabled" : "disabled"} /> : null}
                  </div>
                </div>
                <div>
                  <strong>Trigger</strong>
                  <span>{playbook.trigger}</span>
                  <strong>Risk</strong>
                  <span><StatusChip status={playbook.risk_level} /></span>
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
                  <button type="button" disabled={!canWrite || Boolean(entry && !entry.enabled)} onClick={() => void preview(playbook)}>Preview</button>
                  <button type="button" disabled={!canWrite || Boolean(entry && !entry.enabled)} onClick={() => void run(playbook)}>Run</button>
                </div>
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
                  <details>
                    <summary onClick={() => { if (!revisions[entry.id]) void showRevisions(entry); }}>History and recovery</summary>
                    {revisions[entry.id] ? (
                      <div className="event-list">
                        {revisions[entry.id].map((revision) => (
                          <article className="event-row" key={revision.id}>
                            <span>Version {revision.version}</span>
                            <span>{revision.created_at}</span>
                            <button type="button" onClick={() => void compareRevision(entry, revision)} disabled={revision.version === entry.version}>Compare to current</button>
                            <button type="button" onClick={() => void restoreRevision(entry, revision)} disabled={!canWrite || revision.version === entry.version}>Restore</button>
                          </article>
                        ))}
                        {diffs[entry.id] ? <pre className="technical-details">Changes: {jsonText(diffs[entry.id])}</pre> : null}
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
              <button type="button" disabled={!canWrite} onClick={() => void toggleSubscription(subscription)}>
                {subscription.enabled ? "Disable" : "Enable"}
              </button>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
