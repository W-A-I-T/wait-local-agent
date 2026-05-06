import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  BookOpenText,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  Database,
  GitBranch,
  KeyRound,
  PlayCircle,
  RefreshCw,
  Send,
  ServerCog,
  ShieldCheck,
  Workflow,
  XCircle
} from "lucide-react";

type ConnectorStatus = {
  id: string;
  name: string;
  status: string;
  message: string;
  write_actions_enabled?: boolean;
  http_probing_enabled?: boolean;
};

type HaloReadResult = {
  status: string;
  message: string;
  count: number;
};

type HaloTicket = {
  id: string;
  summary: string;
  status: string;
  priority: string;
  client_name: string;
};

type ApprovalRequest = {
  id: number;
  subject_id: string;
  action_type: string;
  status: string;
  comment: string;
  execution_status: string;
  execution_message: string;
};

type EventHistory = {
  id: number;
  event_type: string;
  subject_id: string;
  status: string;
  message: string;
};

type HaloTicketsResponse = {
  result: HaloReadResult;
  items: HaloTicket[];
};

const actionTypes = [
  "add_note",
  "draft_response",
  "update_status",
  "assign_technician",
  "update_ticket_fields"
];

const defaultFieldText = "note=Reviewed by WAIT Local Agent";

export function App() {
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [writeHealth, setWriteHealth] = useState<HaloReadResult>({
    status: "blocked",
    message: "Loading HaloPSA write health.",
    count: 0
  });
  const [haloTickets, setHaloTickets] = useState<HaloTicket[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequest[]>([]);
  const [eventHistory, setEventHistory] = useState<EventHistory[]>([]);
  const [selectedTicketId, setSelectedTicketId] = useState("");
  const [manualTicketId, setManualTicketId] = useState("");
  const [actionType, setActionType] = useState(actionTypes[0]);
  const [fieldText, setFieldText] = useState(defaultFieldText);
  const [statusMessage, setStatusMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | "draft" | null>(null);

  const haloConnector = connectors.find((connector) => connector.id === "halopsa");
  const liveWritesReady = writeHealth.status === "ready";
  const targetTicketId = selectedTicketId || manualTicketId.trim();
  const isHaloApproval = (request: ApprovalRequest) => request.action_type.startsWith("halopsa.");

  const pendingApprovals = useMemo(
    () => approvalRequests.filter((request) => request.status === "pending"),
    [approvalRequests]
  );

  async function refresh() {
    setLoading(true);
    try {
      const [connectorRows, writeState, ticketResponse, approvals, events] = await Promise.all([
        apiGet<ConnectorStatus[]>("/connectors", []),
        apiGet<HaloReadResult>("/connectors/halopsa/write-health", writeHealth),
        apiGet<HaloTicketsResponse>("/connectors/halopsa/tickets", {
          result: { status: "blocked", message: "Tickets unavailable.", count: 0 },
          items: []
        }),
        apiGet<ApprovalRequest[]>("/approval-requests", []),
        apiGet<EventHistory[]>("/event-history", [])
      ]);
      setConnectors(connectorRows);
      setWriteHealth(writeState);
      setHaloTickets(ticketResponse.items);
      setApprovalRequests(approvals);
      setEventHistory(events);
      if (!selectedTicketId && ticketResponse.items[0]) {
        setSelectedTicketId(ticketResponse.items[0].id);
      }
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to refresh dashboard.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function createDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!targetTicketId) {
      setStatusMessage("Choose a HaloPSA ticket or enter a ticket id.");
      return;
    }
    setBusyId("draft");
    try {
      const draft = await apiPost<{ approval_request_id: number }>(
        `/connectors/halopsa/tickets/${encodeURIComponent(targetTicketId)}/drafts`,
        { action_type: actionType, fields: parseFields(fieldText) }
      );
      setStatusMessage(`Draft created as approval request ${draft.approval_request_id}.`);
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Draft creation failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function updateApproval(requestId: number, status: "approved" | "rejected") {
    setBusyId(requestId);
    try {
      const approval = await apiPost<ApprovalRequest>(`/approval-requests/${requestId}`, {
        status,
        comment: status === "approved" ? "Approved from WAIT dashboard" : "Rejected from dashboard"
      });
      setStatusMessage(
        `${approval.action_type} ${status}; execution ${approval.execution_status}.`
      );
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Approval update failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function executeApproval(requestId: number) {
    setBusyId(requestId);
    try {
      const approval = await apiPost<ApprovalRequest>(
        `/connectors/halopsa/approval-requests/${requestId}/execute`,
        {}
      );
      setStatusMessage(`${approval.action_type} execution ${approval.execution_status}.`);
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Execution failed.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar" aria-label="Workspace navigation">
        <div className="brand">
          <ShieldCheck size={28} aria-hidden="true" />
          <div>
            <strong>WAIT Local Agent</strong>
            <span>Local MSP appliance</span>
          </div>
        </div>
        <nav>
          <a className="active" href="#tickets">
            <ClipboardList size={18} aria-hidden="true" />
            Tickets
          </a>
          <a href="#approvals">
            <ClipboardCheck size={18} aria-hidden="true" />
            Approvals
          </a>
          <a href="#draft">
            <Send size={18} aria-hidden="true" />
            Draft Write
          </a>
          <a href="#connectors">
            <GitBranch size={18} aria-hidden="true" />
            Connectors
          </a>
          <a href="#events">
            <Activity size={18} aria-hidden="true" />
            Events
          </a>
          <a href="#settings">
            <Database size={18} aria-hidden="true" />
            Settings
          </a>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>HaloPSA Live Operations</h1>
            <p>Approval-gated ticket writes, connector health, and local audit history.</p>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" type="button" onClick={() => void refresh()}>
              <RefreshCw size={17} aria-hidden="true" />
              Refresh
            </button>
            <div className={`status-pill ${liveWritesReady ? "" : "danger"}`}>
              {liveWritesReady ? (
                <CheckCircle2 size={18} aria-hidden="true" />
              ) : (
                <XCircle size={18} aria-hidden="true" />
              )}
              {writeHealth.status}
            </div>
          </div>
        </header>

        {statusMessage ? <div className="notice">{statusMessage}</div> : null}

        <section id="connectors" className="panel">
          <div className="panel-heading">
            <h2>Connector Readiness</h2>
            <span>{loading ? "loading" : "live"}</span>
          </div>
          <div className="connector-summary">
            <div>
              <strong>HaloPSA</strong>
              <span>{haloConnector?.message || "Connector status unavailable."}</span>
            </div>
            <em>{haloConnector?.status || "unknown"}</em>
          </div>
          <div className="flag-grid">
            <span>HTTP probing: {haloConnector?.http_probing_enabled ? "enabled" : "disabled"}</span>
            <span>Write actions: {haloConnector?.write_actions_enabled ? "enabled" : "disabled"}</span>
            <span>Write health: {writeHealth.message}</span>
          </div>
        </section>

        <section className="grid">
          <article id="tickets" className="panel">
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
                    setSelectedTicketId(ticket.id);
                    setManualTicketId("");
                  }}
                >
                  <strong>{ticket.id}</strong>
                  <span>{ticket.summary || "No summary"}</span>
                  <em>{ticket.status || "unknown"}</em>
                </button>
              ))}
              {haloTickets.length === 0 ? (
                <p>Live ticket reads are unavailable or returned no tickets.</p>
              ) : null}
            </div>
          </article>

          <article id="draft" className="panel">
            <div className="panel-heading">
              <h2>Draft HaloPSA Write</h2>
              <span>approval required</span>
            </div>
            <form className="draft-form" onSubmit={(event) => void createDraft(event)}>
              <label>
                Ticket id
                <input
                  placeholder="HALO ticket id"
                  value={manualTicketId || selectedTicketId}
                  onChange={(event) => {
                    setManualTicketId(event.target.value);
                    setSelectedTicketId("");
                  }}
                />
              </label>
              <label>
                Action
                <select value={actionType} onChange={(event) => setActionType(event.target.value)}>
                  {actionTypes.map((action) => (
                    <option key={action} value={action}>
                      {action}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Fields
                <textarea
                  value={fieldText}
                  onChange={(event) => setFieldText(event.target.value)}
                  rows={5}
                />
              </label>
              <button disabled={!targetTicketId || busyId === "draft"} type="submit">
                <Send size={17} aria-hidden="true" />
                Create Draft
              </button>
            </form>
          </article>

          <article id="approvals" className="panel approvals-panel">
            <div className="panel-heading">
              <h2>Approval Queue</h2>
              <span>{pendingApprovals.length} pending</span>
            </div>
            <div className="stack-list">
              {approvalRequests.map((request) => (
                <div className="approval-row live" key={request.id}>
                  <div>
                    <strong>{request.action_type}</strong>
                    <span>{request.subject_id}</span>
                  </div>
                  <p>{request.execution_message || request.comment || "Waiting for review"}</p>
                  <em>{request.status} / {request.execution_status}</em>
                  <div className="row-actions">
                    <button
                      disabled={
                        busyId === request.id ||
                        request.status !== "pending" ||
                        (isHaloApproval(request) && !liveWritesReady)
                      }
                      type="button"
                      onClick={() => void updateApproval(request.id, "approved")}
                    >
                      <CheckCircle2 size={16} aria-hidden="true" />
                      Approve
                    </button>
                    <button
                      disabled={busyId === request.id || request.status !== "pending"}
                      type="button"
                      onClick={() => void updateApproval(request.id, "rejected")}
                    >
                      <XCircle size={16} aria-hidden="true" />
                      Reject
                    </button>
                    <button
                      disabled={
                        busyId === request.id ||
                        request.status !== "approved" ||
                        !isHaloApproval(request) ||
                        !liveWritesReady
                      }
                      type="button"
                      onClick={() => void executeApproval(request.id)}
                    >
                      <PlayCircle size={16} aria-hidden="true" />
                      Execute
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article id="events" className="panel">
            <div className="panel-heading">
              <h2>Event History</h2>
              <span>{eventHistory.length} events</span>
            </div>
            <div className="event-list">
              {eventHistory.map((event) => (
                <div className="event-row" key={event.id}>
                  <span>{event.event_type}</span>
                  <strong>{event.subject_id}</strong>
                  <em>{event.status}</em>
                  <p>{event.message}</p>
                </div>
              ))}
            </div>
          </article>

          <article id="settings" className="panel settings-panel">
            <div className="panel-heading">
              <h2>Provider And Secrets</h2>
              <span>local env</span>
            </div>
            <dl className="settings-list">
              <div>
                <dt>Write gate</dt>
                <dd>
                  <ServerCog size={15} aria-hidden="true" />
                  {writeHealth.message}
                </dd>
              </div>
              <div>
                <dt>Secrets</dt>
                <dd>
                  <KeyRound size={15} aria-hidden="true" />
                  Redacted from API, CLI, and UI output
                </dd>
              </div>
              <div>
                <dt>Knowledge</dt>
                <dd>
                  <BookOpenText size={15} aria-hidden="true" />
                  Local citations remain available for draft text
                </dd>
              </div>
              <div>
                <dt>Workflows</dt>
                <dd>
                  <Workflow size={15} aria-hidden="true" />
                  Approval requests stay local until execution
                </dd>
              </div>
            </dl>
          </article>
        </section>
      </section>
    </main>
  );
}

async function apiGet<T>(path: string, fallback: T): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    return fallback;
  }
  return (await response.json()) as T;
}

async function apiPost<T>(path: string, body: object): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function parseFields(text: string): Record<string, string> {
  return Object.fromEntries(
    text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [key, ...rest] = line.split("=");
        return [key.trim(), rest.join("=").trim()];
      })
      .filter(([key]) => key)
  );
}
