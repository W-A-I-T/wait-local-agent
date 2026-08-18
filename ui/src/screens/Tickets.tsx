import { FormEvent, useEffect, useMemo, useState } from "react";
import { Send } from "lucide-react";
import { ApiRequestError, apiFetch } from "../api/client";
import { defaultFieldText, useDashboard } from "../app/DashboardContext";
import { parseFields } from "../lib/fields";
import type {
  EndUserMessage,
  Ticket,
  TicketContext,
  TicketNote,
  TicketStatusHistory,
  TicketSummaryResponse
} from "../api/types";

type TicketTab = "summary" | "notes" | "status-history" | "context";
const tabs: Array<{ id: TicketTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "notes", label: "Notes" },
  { id: "status-history", label: "Status History" },
  { id: "context", label: "Context" }
];

function displayValue(value: unknown, fallback = "Not recorded") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function formatDate(value: unknown) {
  if (!value) return "Not dated";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function tabPath(ticketId: string, tab: TicketTab) {
  const endpoint = tab === "status-history" ? "status-history" : tab;
  return `/tickets/${encodeURIComponent(ticketId)}/${endpoint}`;
}

export function Tickets() {
  const {
    selectedClientId,
    clients = [],
    selectedTicketId,
    selectTicket,
    actionTypes = [],
    canWrite,
    busyId,
    createDraft
  } = useDashboard();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [activeTab, setActiveTab] = useState<TicketTab>("summary");
  const [tabLoading, setTabLoading] = useState(false);
  const [tabError, setTabError] = useState("");
  const [ticketSummary, setTicketSummary] = useState<TicketSummaryResponse | null>(null);
  const [notes, setNotes] = useState<TicketNote[]>([]);
  const [statusHistory, setStatusHistory] = useState<TicketStatusHistory[]>([]);
  const [context, setContext] = useState<TicketContext | null>(null);
  const [contextNotFound, setContextNotFound] = useState(false);

  const [actionType, setActionType] = useState(actionTypes[0] ?? "add_note");
  const [fieldText, setFieldText] = useState(defaultFieldText);
  const [validationMessage, setValidationMessage] = useState("");
  const [approvalStatus, setApprovalStatus] = useState("pending");
  const [approvalComment, setApprovalComment] = useState("");
  const [endUserMessages, setEndUserMessages] = useState<EndUserMessage[]>([]);
  const [endUserReply, setEndUserReply] = useState("");
  const [endUserMessageError, setEndUserMessageError] = useState("");
  const [endUserMessageStatus, setEndUserMessageStatus] = useState("");
  const [endUserMessageBusy, setEndUserMessageBusy] = useState(false);
  const [haloSyncTicketId, setHaloSyncTicketId] = useState("");
  const [haloSyncMessageId, setHaloSyncMessageId] = useState("");
  const [haloSyncStatus, setHaloSyncStatus] = useState("");
  const [haloSyncBusy, setHaloSyncBusy] = useState(false);

  const selectedTicket = useMemo(
    () => tickets.find((ticket) => ticket.id === selectedTicketId) ?? null,
    [selectedTicketId, tickets]
  );
  const clientNames = useMemo(() => new Map(clients.map((client) => [client.client_id, client.name])), [clients]);
  const ticketId = selectedTicket?.id || selectedTicketId;
  const [manualTicketId, setManualTicketId] = useState("");
  const actionTicketId = ticketId || manualTicketId.trim();

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    setListError("");
    const query = selectedClientId ? `?client_id=${encodeURIComponent(selectedClientId)}` : "";
    void apiFetch<Ticket[]>(`/tickets${query}`)
      .then((result) => {
        if (cancelled) return;
        const rows = Array.isArray(result) ? result : [];
        setTickets(rows);
        if (selectedTicketId && !rows.some((ticket) => ticket.id === selectedTicketId)) selectTicket("");
      })
      .catch((error) => {
        if (!cancelled) setListError(error instanceof Error ? error.message : "Unable to load tickets.");
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedClientId]);

  useEffect(() => {
    if (!actionTicketId) return;
    setActiveTab("summary");
    setTicketSummary(null);
    setNotes([]);
    setStatusHistory([]);
    setContext(null);
    setContextNotFound(false);
    setTabError("");
  }, [ticketId]);

  useEffect(() => {
    if (!ticketId) return;
    let cancelled = false;
    setTabLoading(true);
    setTabError("");
    if (activeTab === "context") setContextNotFound(false);
    void apiFetch< TicketSummaryResponse | TicketNote[] | TicketStatusHistory[] | TicketContext >(tabPath(ticketId, activeTab))
      .then((result) => {
        if (cancelled) return;
        if (activeTab === "summary") setTicketSummary(result as TicketSummaryResponse);
        if (activeTab === "notes") setNotes(Array.isArray(result) ? result as TicketNote[] : []);
        if (activeTab === "status-history") setStatusHistory(Array.isArray(result) ? result as TicketStatusHistory[] : []);
        if (activeTab === "context") setContext(result as TicketContext);
      })
      .catch((error) => {
        if (cancelled) return;
        if (activeTab === "context" && error instanceof ApiRequestError && error.status === 404) {
          setContextNotFound(true);
          setContext(null);
        } else {
          setTabError(error instanceof Error ? error.message : "Unable to load ticket details.");
        }
      })
      .finally(() => {
        if (!cancelled) setTabLoading(false);
      });
    return () => { cancelled = true; };
  }, [activeTab, ticketId]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!actionTicketId) {
      setValidationMessage("Choose a ticket before creating an action draft.");
      return;
    }
    setValidationMessage("");
    void createDraft(actionTicketId, actionType, parseFields(fieldText));
  }

  async function postTicketTriage() {
    if (!actionTicketId) return;
    try {
      await apiFetch(`/tickets/${encodeURIComponent(actionTicketId)}/approvals`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: approvalStatus, comment: approvalComment })
      });
      setTabError("Triage update sent.");
    } catch (error) {
      setTabError(error instanceof Error ? error.message : "Unable to post triage.");
    }
  }

  async function loadEndUserMessages() {
    if (!actionTicketId) return;
    setEndUserMessageError("");
    try {
      setEndUserMessages(await apiFetch<EndUserMessage[]>(`/tickets/${encodeURIComponent(actionTicketId)}/end-user-messages`));
    } catch (error) {
      setEndUserMessageError(error instanceof Error ? error.message : "Unable to load the customer conversation.");
    }
  }

  async function sendEndUserReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!actionTicketId || !endUserReply.trim() || !canWrite) return;
    setEndUserMessageBusy(true); setEndUserMessageError(""); setEndUserMessageStatus("");
    try {
      const created = await apiFetch<EndUserMessage>(`/tickets/${encodeURIComponent(actionTicketId)}/end-user-messages`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: endUserReply.trim() })
      });
      setEndUserMessages((current) => [...current, created]); setEndUserReply("");
      setEndUserMessageStatus("Reply added to the local customer conversation.");
    } catch (error) {
      setEndUserMessageError(error instanceof Error ? error.message : "Unable to add the customer reply.");
    } finally { setEndUserMessageBusy(false); }
  }

  async function draftHaloSync(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const messageId = Number(haloSyncMessageId);
    if (!actionTicketId || !Number.isInteger(messageId) || !haloSyncTicketId.trim() || !canWrite) return;
    setHaloSyncBusy(true); setHaloSyncStatus(""); setEndUserMessageError("");
    try {
      const draft = await apiFetch<{ approval_request_id: number }>(`/tickets/${encodeURIComponent(actionTicketId)}/end-user-messages/${messageId}/halopsa-drafts`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ external_ticket_id: haloSyncTicketId.trim() })
      });
      setHaloSyncStatus(`HaloPSA approval draft ${draft.approval_request_id} created. Review it before execution.`);
    } catch (error) {
      setEndUserMessageError(error instanceof Error ? error.message : "Unable to prepare the HaloPSA sync.");
    } finally { setHaloSyncBusy(false); }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Operations</p><h2>Tickets</h2></div><span>{tickets.length} visible</span></div>
        <p className="screen-note">Review tickets from every connected provider in the selected client scope.</p>
        {listError ? <div className="notice danger" role="alert">{listError}</div> : null}
        {listLoading ? <p className="screen-note" aria-busy="true">Loading tickets…</p> : tickets.length === 0 ? <div className="empty-state"><h3>No tickets are visible.</h3><p>There are no tickets in the current client scope.</p></div> : (
          <div className="clients-table-wrap"><table className="clients-table"><thead><tr><th scope="col">Ticket</th><th scope="col">Client</th><th scope="col">Status</th><th scope="col">Priority</th><th scope="col">Source</th><th scope="col">External ID</th></tr></thead><tbody>
            {tickets.map((ticket) => <tr key={ticket.id} className={ticket.id === selectedTicketId ? "selected" : undefined}><td><button className="table-link" type="button" onClick={() => selectTicket(ticket.id)}>{displayValue(ticket.summary || ticket.subject, "Untitled ticket")}</button><div className="screen-note">{ticket.id}</div></td><td>{clientNames.get(ticket.client_id ?? "") || displayValue(ticket.client_id, "Current scope")}</td><td>{displayValue(ticket.status, "Unknown")}</td><td>{displayValue(ticket.priority, "Unprioritized")}</td><td>{displayValue(ticket.source_system, "Local")}</td><td><code>{displayValue(ticket.external_id, "—")}</code></td></tr>)}
          </tbody></table></div>
        )}
      </section>

      {!ticketId ? <section className="panel empty-state"><h3>Select a ticket to open its workspace.</h3><p>Summary, notes, status changes, context, and actions will appear here.</p></section> : null}
      {ticketId ? <>
        <section className="panel" aria-labelledby="ticket-detail-heading">
          <div className="panel-heading"><div><p className="eyebrow">Ticket workspace</p><h2 id="ticket-detail-heading">{displayValue(selectedTicket?.summary || selectedTicket?.subject, "Ticket detail")}</h2><span>{ticketId} · {displayValue(selectedTicket?.source_system, "Local")}</span></div><span>{displayValue(selectedTicket?.status, "Unknown")}</span></div>
          <div className="tab-list" role="tablist" aria-label="Ticket detail"><div className="row-actions">{tabs.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={activeTab === tab.id} className={activeTab === tab.id ? "selected" : "secondary-button"} onClick={() => setActiveTab(tab.id)}>{tab.label}</button>)}</div></div>
          {tabLoading ? <p className="screen-note" aria-busy="true">Loading {tabs.find((tab) => tab.id === activeTab)?.label.toLowerCase()}…</p> : null}
          {tabError ? <div className="notice danger" role="alert">{tabError}</div> : null}
          {!tabLoading && activeTab === "summary" && ticketSummary ? <article className="approval-card"><strong>Classification: {displayValue(ticketSummary.classification)}</strong><p>{displayValue(ticketSummary.summary)}</p><p>Suggested response: {displayValue(ticketSummary.suggested_response)}</p>{ticketSummary.sources?.length ? <p className="screen-note">{ticketSummary.sources.length} supporting source{ticketSummary.sources.length === 1 ? "" : "s"}</p> : null}</article> : null}
          {!tabLoading && activeTab === "notes" ? notes.length ? <div className="stack-list">{notes.map((note) => <article className="approval-card" key={note.id}><strong>{displayValue(note.author, "Unknown author")}</strong><span>{formatDate(note.created_at)}</span><p>{note.body}</p></article>)}</div> : <p className="screen-note">No notes have been recorded for this ticket.</p> : null}
          {!tabLoading && activeTab === "status-history" ? statusHistory.length ? <div className="stack-list">{statusHistory.map((item, index) => <article className="approval-card" key={item.id ?? `${item.at}-${index}`}><strong>{displayValue(item.from_status ?? item.from, "No prior status")} → {displayValue(item.to_status ?? item.to ?? item.status, "Unknown")}</strong><span>{formatDate(item.created_at ?? item.at)} · {displayValue(item.actor ?? item.changed_by, "System")}</span></article>)}</div> : <p className="screen-note">No status changes have been recorded for this ticket.</p> : null}
          {!tabLoading && activeTab === "context" ? contextNotFound || !context || (!(context.refs?.length) && !(context.links?.length)) ? <div className="empty-state"><h3>No linked context yet.</h3><p>This ticket is not currently represented in the operational context graph.</p></div> : <div className="stack-list"><section><h3>Entity references</h3>{context.refs?.length ? <div className="table-list">{context.refs.map((ref, index) => <article className="approval-card" key={`${String(ref.entity_type ?? "entity")}-${String(ref.external_id ?? index)}`}><strong>{displayValue(ref.entity_type, "Entity")}</strong><p>{displayValue(ref.external_id ?? ref.id ?? ref.name)}</p></article>)}</div> : <p className="screen-note">No entity references are linked.</p>}</section><section><h3>Links</h3>{context.links?.length ? <div className="table-list">{context.links.map((link, index) => <article className="approval-card" key={`${String(link.link_type ?? link.type ?? "link")}-${index}`}><strong>{displayValue(link.link_type ?? link.type, "Related")}</strong><p>{displayValue(link.from ?? link.source)} → {displayValue(link.to ?? link.target)}</p></article>)}</div> : <p className="screen-note">No relationships are linked.</p>}</section></div> : null}
        </section>

      </> : null}

      <section className="panel">
          <div className="panel-heading"><h2>Actions</h2><span>{canWrite ? "approval drafts enabled" : "read-only"}</span></div>
          {validationMessage ? <div className="notice danger" role="alert">{validationMessage}</div> : null}
          <form className="draft-form" onSubmit={handleSubmit}><label>Ticket ID<input placeholder="EUS-..." value={manualTicketId || ticketId} onChange={(event) => setManualTicketId(event.target.value)} /></label><label>Action<select value={actionType} onChange={(event) => setActionType(event.target.value)}>{actionTypes.map((action) => <option key={action} value={action}>{action}</option>)}</select></label><label>Draft payload<textarea value={fieldText} onChange={(event) => setFieldText(event.target.value)} rows={4} /></label><button disabled={!actionTicketId || !canWrite || busyId === "draft"} type="submit"><Send size={17} aria-hidden="true" />{busyId === "draft" ? "Creating…" : "Create draft"}</button></form>
          <div className="draft-form"><h3>Triage</h3><div className="row-actions"><select aria-label="Triage status" value={approvalStatus} onChange={(event) => setApprovalStatus(event.target.value)}><option value="approved">approved</option><option value="rejected">rejected</option><option value="pending">pending</option></select><button type="button" disabled={!canWrite} onClick={() => void postTicketTriage()}>Post triage</button></div><label>Triage comment<textarea value={approvalComment} onChange={(event) => setApprovalComment(event.target.value)} rows={3} /></label></div>
          <div className="draft-form"><h3>End-user messages</h3><button type="button" onClick={() => void loadEndUserMessages()}>Load conversation</button>{endUserMessageStatus ? <div className="notice" role="status">{endUserMessageStatus}</div> : null}{haloSyncStatus ? <div className="notice" role="status">{haloSyncStatus}</div> : null}{endUserMessageError ? <div className="notice danger" role="alert">{endUserMessageError}</div> : null}{endUserMessages.length ? <div className="end-user-messages operator-messages">{endUserMessages.map((item) => <p key={item.id}><strong>{item.role === "support" ? "Support" : "Requester"}</strong><span>{item.body}</span></p>)}</div> : <p className="screen-note">Load the local requester conversation. Internal notes are in the Notes tab.</p>}<form className="draft-form" onSubmit={(event) => void sendEndUserReply(event)}><label>Reply to requester<textarea required maxLength={10000} rows={3} value={endUserReply} onChange={(event) => setEndUserReply(event.target.value)} placeholder="Write a response for the local end-user portal" /></label><button type="submit" disabled={!canWrite || endUserMessageBusy || !endUserReply.trim()}>{endUserMessageBusy ? "Sending…" : "Add support reply"}</button></form>{endUserMessages.length ? <form className="draft-form" onSubmit={(event) => void draftHaloSync(event)}><label>HaloPSA ticket ID<input value={haloSyncTicketId} onChange={(event) => setHaloSyncTicketId(event.target.value)} placeholder="Provider ticket ID" /></label><label>Message to sync<select value={haloSyncMessageId} onChange={(event) => setHaloSyncMessageId(event.target.value)}><option value="">Choose a local message</option>{endUserMessages.map((item) => <option key={item.id} value={item.id}>{item.id}: {item.role === "support" ? "Support" : "Requester"}</option>)}</select></label><button type="submit" disabled={!canWrite || haloSyncBusy || !haloSyncTicketId.trim() || !haloSyncMessageId}>{haloSyncBusy ? "Preparing…" : "Prepare HaloPSA approval"}</button><p className="screen-note">The configured tenant mapping is checked before an approval draft is created.</p></form> : null}</div>
        </section>
    </div>
  );
}
