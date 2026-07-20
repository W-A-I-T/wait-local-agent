import { FormEvent, useState } from "react";
import { Send } from "lucide-react";
import { apiFetch } from "../api/client";
import { defaultFieldText, useDashboard } from "../app/DashboardContext";
import { parseFields } from "../lib/fields";
import type { TicketSummaryResponse } from "../api/types";

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
    </div>
  );
}
