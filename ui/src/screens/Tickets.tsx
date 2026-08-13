import { FormEvent, useState } from "react";
import { Send } from "lucide-react";
import { apiFetch } from "../api/client";
import { defaultFieldText, useDashboard } from "../app/DashboardContext";
import { parseFields } from "../lib/fields";
import type { EndUserMessage, TicketSummaryResponse } from "../api/types";

export function Tickets() {
  const {
    haloTickets,
    selectedTicketId,
    selectTicket,
    actionTypes,
    canWrite,
    busyId,
    createDraft
  } = useDashboard();
  const [manualTicketId, setManualTicketId] = useState("");
  const [actionType, setActionType] = useState(actionTypes[0]);
  const [fieldText, setFieldText] = useState(defaultFieldText);
  const [validationMessage, setValidationMessage] = useState("");
  const [summaryTicketId, setSummaryTicketId] = useState("");
  const [ticketSummary, setTicketSummary] = useState<TicketSummaryResponse | null>(null);
  const [summaryError, setSummaryError] = useState("");
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
  const targetTicketId = manualTicketId.trim() || selectedTicketId;

  function resolveTicketId(): string {
    return targetTicketId || manualTicketId || selectedTicketId;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticketId = resolveTicketId();
    if (!ticketId) {
      setValidationMessage("Choose a HaloPSA ticket or enter a ticket id.");
      return;
    }
    setValidationMessage("");
    void createDraft(ticketId, actionType, parseFields(fieldText));
  }

  async function loadSummary() {
    const ticketId = summaryTicketId || resolveTicketId();
    if (!ticketId) {
      setSummaryError("Choose a ticket id first.");
      return;
    }
    setSummaryError("");
    try {
      const summary = await apiFetch<TicketSummaryResponse>(`/tickets/${encodeURIComponent(ticketId)}/summary`);
      setTicketSummary(summary);
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : "Unable to fetch ticket summary.");
    }
  }

  async function postTicketTriage() {
    const ticketId = summaryTicketId || resolveTicketId();
    if (!ticketId) {
      setSummaryError("Choose a ticket id first.");
      return;
    }
    try {
      await apiFetch(`/tickets/${encodeURIComponent(ticketId)}/approvals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: approvalStatus,
          comment: approvalComment
        })
      });
      setSummaryError("Triage update sent.");
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : "Unable to post triage.");
    }
  }

  async function loadEndUserMessages() {
    const ticketId = summaryTicketId || resolveTicketId();
    if (!ticketId) {
      setEndUserMessageError("Choose a ticket id first.");
      return;
    }
    setEndUserMessageError("");
    setEndUserMessageStatus("");
    try {
      setEndUserMessages(await apiFetch<EndUserMessage[]>(`/tickets/${encodeURIComponent(ticketId)}/end-user-messages`));
    } catch (error) {
      setEndUserMessageError(error instanceof Error ? error.message : "Unable to load the customer conversation.");
    }
  }

  async function sendEndUserReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticketId = summaryTicketId || resolveTicketId();
    if (!ticketId || !endUserReply.trim() || !canWrite) {
      return;
    }
    setEndUserMessageBusy(true);
    setEndUserMessageError("");
    setEndUserMessageStatus("");
    try {
      const created = await apiFetch<EndUserMessage>(`/tickets/${encodeURIComponent(ticketId)}/end-user-messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: endUserReply.trim() })
      });
      setEndUserMessages((current) => [...current, created]);
      setEndUserReply("");
      setEndUserMessageStatus("Reply added to the local customer conversation.");
    } catch (error) {
      setEndUserMessageError(error instanceof Error ? error.message : "Unable to add the customer reply.");
    } finally {
      setEndUserMessageBusy(false);
    }
  }

  async function draftHaloSync(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticketId = summaryTicketId || resolveTicketId();
    const messageId = Number(haloSyncMessageId);
    if (!ticketId || !Number.isInteger(messageId) || !haloSyncTicketId.trim() || !canWrite) {
      return;
    }
    setHaloSyncBusy(true);
    setHaloSyncStatus("");
    setEndUserMessageError("");
    try {
      const draft = await apiFetch<{ approval_request_id: number }>(
        `/tickets/${encodeURIComponent(ticketId)}/end-user-messages/${messageId}/halopsa-drafts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ external_ticket_id: haloSyncTicketId.trim() })
        }
      );
      setHaloSyncStatus(`HaloPSA approval draft ${draft.approval_request_id} created. Review it before execution.`);
    } catch (error) {
      setEndUserMessageError(error instanceof Error ? error.message : "Unable to prepare the HaloPSA sync.");
    } finally {
      setHaloSyncBusy(false);
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <h2>HaloPSA Tickets</h2>
          <span>{haloTickets.length} loaded</span>
        </div>
        <div className="stack-list">
          {haloTickets.map((ticket) => (
            <button
              className={`ticket-select ${selectedTicketId === ticket.id ? "selected" : ""}`}
              key={ticket.id}
              type="button"
              onClick={() => {
                selectTicket(ticket.id);
                setManualTicketId("");
              }}
            >
              <strong>{ticket.id}</strong>
              <span>{ticket.summary || "No summary"}</span>
              <em>{ticket.status || "unknown"}</em>
            </button>
          ))}
          {haloTickets.length === 0 ? <p>Live ticket reads are unavailable or returned no tickets.</p> : null}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Ticket actions</h2>
          <span>{canWrite ? "write enabled" : "read-only"}</span>
        </div>
        {validationMessage ? <div className="notice danger">{validationMessage}</div> : null}
        <form className="draft-form" onSubmit={handleSubmit}>
          <label>
            Ticket id
            <input
              placeholder="HALO ticket id"
              value={manualTicketId || selectedTicketId}
              onChange={(event) => {
                setManualTicketId(event.target.value);
                selectTicket("");
              }}
            />
          </label>
          <label>
            Action
            <select value={actionType} onChange={(event) => setActionType(event.target.value)}>
              {actionTypes.map((action) => (
                <option key={action} value={action}>{action}</option>
              ))}
            </select>
          </label>
          <label>
            Draft payload
            <textarea value={fieldText} onChange={(event) => setFieldText(event.target.value)} rows={5} />
          </label>
          <button disabled={!resolveTicketId() || busyId === "draft" || !canWrite} type="submit">
            <Send size={17} aria-hidden="true" />
            Create Draft
          </button>
        </form>
      </section>

      <section className="panel knowledge-panel">
        <div className="panel-heading">
          <h2>Triage and summarize</h2>
          <span>{ticketSummary ? "summary ready" : "idle"}</span>
        </div>
        <div className="draft-form">
          <label>
            Ticket id
            <input
              value={summaryTicketId}
              onChange={(event) => setSummaryTicketId(event.target.value)}
              placeholder={resolveTicketId() || "HALO-1"}
            />
          </label>
          <div className="row-actions">
            <button type="button" onClick={() => void loadSummary()} disabled={busyId === "draft"}>Run summary</button>
            <select value={approvalStatus} onChange={(event) => setApprovalStatus(event.target.value)}>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="pending">pending</option>
            </select>
            <button type="button" disabled={!canWrite} onClick={() => void postTicketTriage()}>Post triage</button>
          </div>
          <label>
            Triage comment
            <textarea
              value={approvalComment}
              onChange={(event) => setApprovalComment(event.target.value)}
              rows={3}
            />
          </label>
        </div>
        {summaryError ? <p className="screen-note">{summaryError}</p> : null}
      {ticketSummary ? (
          <div className="table-list">
            <article className="approval-card">
              <strong>Classification: {ticketSummary.classification}</strong>
              <p>{ticketSummary.summary}</p>
              <p>Suggested reply: {ticketSummary.suggested_response}</p>
            </article>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Customer conversation</h2>
          <span>{endUserMessages.length ? `${endUserMessages.length} messages` : "local end-user thread"}</span>
        </div>
        <div className="draft-form">
          <label>
            Ticket id
            <input value={summaryTicketId} onChange={(event) => setSummaryTicketId(event.target.value)} placeholder={resolveTicketId() || "EUS-..."} />
          </label>
          <div className="row-actions">
            <button type="button" onClick={() => void loadEndUserMessages()} disabled={!summaryTicketId && !resolveTicketId()}>Load conversation</button>
          </div>
        </div>
        {endUserMessageStatus ? <div className="notice" role="status">{endUserMessageStatus}</div> : null}
        {haloSyncStatus ? <div className="notice" role="status">{haloSyncStatus}</div> : null}
        {endUserMessageError ? <div className="notice danger" role="alert">{endUserMessageError}</div> : null}
        {endUserMessages.length ? <div className="end-user-messages operator-messages">{endUserMessages.map((item) => <p key={item.id}><strong>{item.role === "support" ? "Support" : "Requester"}</strong><span>{item.body}</span></p>)}</div> : <p className="screen-note">Load a local end-user thread to review requester messages. Internal ticket notes are separate.</p>}
        {endUserMessages.length ? <form className="draft-form" onSubmit={(event) => void draftHaloSync(event)}>
          <label>
            HaloPSA ticket ID
            <input value={haloSyncTicketId} onChange={(event) => setHaloSyncTicketId(event.target.value)} placeholder="HALO-42" />
          </label>
          <label>
            Message to sync
            <select value={haloSyncMessageId} onChange={(event) => setHaloSyncMessageId(event.target.value)}>
              <option value="">Choose a local message</option>
              {endUserMessages.map((item) => <option key={item.id} value={item.id}>{item.id}: {item.role === "support" ? "Support" : "Requester"}</option>)}
            </select>
          </label>
          <button type="submit" disabled={!canWrite || haloSyncBusy || !haloSyncTicketId.trim() || !haloSyncMessageId}>{haloSyncBusy ? "Preparing…" : "Prepare HaloPSA approval"}</button>
          <p className="screen-note">The configured tenant mapping is checked before an approval draft is created. Approval is still required.</p>
        </form> : null}
        <form className="draft-form" onSubmit={(event) => void sendEndUserReply(event)}>
          <label>
            Reply to requester
            <textarea required maxLength={10000} rows={3} value={endUserReply} onChange={(event) => setEndUserReply(event.target.value)} placeholder="Write a response for the local end-user portal" />
          </label>
          <button type="submit" disabled={!canWrite || endUserMessageBusy || !endUserReply.trim()}>{endUserMessageBusy ? "Sending…" : "Add support reply"}</button>
        </form>
        {!canWrite ? <p className="screen-note">A technician or administrator role is required to add a support reply.</p> : null}
      </section>
    </div>
  );
}
