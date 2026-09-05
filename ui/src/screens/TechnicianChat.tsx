import { FormEvent, useCallback, useEffect, useState } from "react";
import { CheckCircle2, MessageSquare, Plus, Send, XCircle } from "lucide-react";
import { apiFetch } from "../api/client";
import { apiFetchForClient } from "../api/scopedFetch";
import { useDashboard } from "../app/DashboardContext";
import { ScopeBadge } from "../components/ScopeBadge";
import { SelectClientNotice } from "../components/SelectClientNotice";
import type { SmartActionRun, TechnicianChatResponse, TechnicianChatSession } from "../api/types";

export function TechnicianChat() {
  const { selectedClientId = "" } = useDashboard();
  // Changing clients discards unsent drafts and detaches in-flight responses
  // from the previous conversation before the new workspace is displayed.
  return <ClientTechnicianChat key={selectedClientId} />;
}

function ClientTechnicianChat() {
  const { canWrite, canWriteExternally = canWrite, selectedClientId = "", isMspAdmin = false } = useDashboard();
  const [sessions, setSessions] = useState<TechnicianChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<TechnicianChatSession | null>(null);
  const [ticketId, setTicketId] = useState("");
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState("");
  const [plan, setPlan] = useState<TechnicianChatResponse["plan"] | null>(null);
  const [error, setError] = useState("");
  const [notificationChannel, setNotificationChannel] = useState<"teams" | "slack">("teams");
  const [notificationRecipient, setNotificationRecipient] = useState("");
  const [notificationSubject, setNotificationSubject] = useState("");
  const [notificationBody, setNotificationBody] = useState("");
  const [notificationBusy, setNotificationBusy] = useState(false);
  const [notificationRuns, setNotificationRuns] = useState<SmartActionRun[]>([]);
  const [notificationLoading, setNotificationLoading] = useState(true);
  const [notificationError, setNotificationError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingSession, setLoadingSession] = useState<string | null>(null);
  const [busy, setBusy] = useState<"create" | "send" | "close" | null>(null);

  const refreshNotificationRuns = useCallback(async () => {
    if (!canWrite) {
      setNotificationLoading(false);
      return;
    }
    setNotificationLoading(true);
    setNotificationError("");
    try {
      const runs = await apiFetchForClient<SmartActionRun[]>(selectedClientId, "/smart-actions/runs");
      setNotificationRuns(runs.filter((run) => run.action_id === "communication-send").slice(0, 12));
    } catch (requestError) {
      setNotificationError(requestError instanceof Error ? requestError.message : "Unable to load notification activity.");
    } finally {
      setNotificationLoading(false);
    }
  }, [canWrite, selectedClientId]);

  const refreshSessions = useCallback(async () => {
    if (!canWrite) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const rows = await apiFetchForClient<TechnicianChatSession[]>(selectedClientId, "/technician/chat/sessions");
      setSessions(rows);
      setActiveSession((current) => {
        if (!current) return rows[0] ?? null;
        const row = rows.find((item) => item.id === current.id);
        return row && row.messages.length > 0 ? row : current;
      });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load technician chat sessions.");
    } finally {
      setLoading(false);
    }
  }, [canWrite, selectedClientId]);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    void refreshNotificationRuns();
  }, [refreshNotificationRuns]);

  async function openSession(sessionId: string) {
    setLoadingSession(sessionId);
    setError("");
    try {
      const session = await apiFetch<TechnicianChatSession>(`/technician/chat/sessions/${encodeURIComponent(sessionId)}`);
      setActiveSession(session);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load that session.");
    } finally {
      setLoadingSession(null);
    }
  }

  async function createSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedClientId) {
      setError("Select a client from the top bar before starting a chat session.");
      return;
    }
    setBusy("create");
    setError("");
    setMessage("");
    setPlan(null);
    try {
      const session = await apiFetch<TechnicianChatSession>("/technician/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: selectedClientId,
          ticket_id: ticketId.trim() || undefined
        })
      });
      setSessions((current) => [session, ...current.filter((row) => row.id !== session.id)]);
      setActiveSession(session);
      setMessage(`Session ${session.id} started.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to start a technician chat session.");
    } finally {
      setBusy(null);
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeSession || !draft.trim() || activeSession.status === "closed" || loadingSession !== null) return;
    setBusy("send");
    setError("");
    setMessage("");
    setPlan(null);
    try {
      const response = await apiFetch<TechnicianChatResponse>(
        `/technician/chat/sessions/${encodeURIComponent(activeSession.id)}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: draft.trim(), ticket_id: ticketId.trim() || undefined })
        }
      );
      setDraft("");
      setMessage(response.message || `Request completed with status ${response.status}.`);
      setPlan(response.plan ?? null);
      await openSession(activeSession.id);
      await refreshSessions();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to send the technician request.");
      await openSession(activeSession.id);
    } finally {
      setBusy(null);
    }
  }

  async function closeSession() {
    if (!activeSession) return;
    setBusy("close");
    setError("");
    try {
      const closed = await apiFetch<TechnicianChatSession>(`/technician/chat/sessions/${encodeURIComponent(activeSession.id)}/close`, { method: "POST" });
      setActiveSession(closed);
      setSessions((current) => current.map((row) => row.id === closed.id ? closed : row));
      setMessage("Session closed. Its operational history remains available for review.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to close the session.");
    } finally {
      setBusy(null);
    }
  }

  async function prepareNotification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!notificationRecipient.trim() || !notificationBody.trim() || !canWriteExternally) return;
    setNotificationBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await apiFetch<{ approval_id?: number; status: string }>("/smart-actions/communication-send/invoke", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: selectedClientId || undefined,
          payload: {
            channel: notificationChannel,
            recipient: notificationRecipient.trim(),
            subject: notificationSubject.trim() || undefined,
            body: notificationBody.trim(),
            ticket_id: ticketId.trim() || undefined
          }
        })
      });
      setMessage(result.approval_id
        ? `${notificationChannel} notification approval ${result.approval_id} created. Review it before delivery.`
        : `${notificationChannel} notification request completed with status ${result.status}.`);
      setNotificationBody("");
      await refreshNotificationRuns();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to prepare the technician notification.");
    } finally {
      setNotificationBusy(false);
    }
  }

  if (!canWrite) {
    return <section className="panel"><div className="panel-heading"><h2>Technician Chat</h2><span>Technician access required</span></div><p>Chat can prepare bounded actions for technicians and administrators. Viewer access does not expose this control.</p></section>;
  }

  return (
    <div className="screen-stack technician-chat-screen">
        <section className="panel">
        <div className="panel-heading"><div><h2>Technician Chat</h2><p className="screen-note">Use the same bounded smart-action catalog as the API and CLI. Requests are parsed, tenant-scoped, audited, and approval-gated where required.</p></div><MessageSquare size={22} aria-hidden="true" /></div>
        {message ? <div className="notice" role="status"><CheckCircle2 size={17} aria-hidden="true" />{message}</div> : null}
        {error ? <div className="notice danger" role="alert"><XCircle size={17} aria-hidden="true" />{error}</div> : null}
        {plan ? <div className="technician-plan" role="status"><strong>Bounded plan preview · {plan.status}</strong>{plan.blocked_reason ? <p>{plan.blocked_reason}</p> : null}{plan.steps.length ? <ol>{plan.steps.map((step) => <li key={`${step.index}-${step.tool_id}`}><strong>{step.name}</strong><span>{step.reason} · {step.approval_required ? "approval required" : "read-only or deterministic"}</span></li>)}</ol> : <p>No approved steps were selected.</p>}</div> : null}
        <form className="draft-form" onSubmit={(event) => void createSession(event)}>
          <div className="grid">
            <p className="screen-note">Scope: <ScopeBadge /></p>
            <label>Ticket id (optional)<input value={ticketId} onChange={(event) => setTicketId(event.target.value)} placeholder="TCK-1001" /></label>
          </div>
          {!selectedClientId && !isMspAdmin ? <SelectClientNotice /> : null}
          <button type="submit" disabled={busy !== null || !selectedClientId} title={!selectedClientId ? "Select a client from the top bar first" : undefined}><Plus size={17} aria-hidden="true" />{busy === "create" ? "Starting…" : "New chat session"}</button>
        </form>
        <form className="draft-form" onSubmit={(event) => void prepareNotification(event)}>
          <div className="panel-heading"><div><h3>Technician notification</h3><p className="screen-note">Prepare a Teams or Slack notification through the existing approval-gated communication action.</p></div></div>
          <div className="grid">
            <label>Notification channel<select aria-label="Notification channel" value={notificationChannel} onChange={(event) => setNotificationChannel(event.target.value as "teams" | "slack")}><option value="teams">Teams</option><option value="slack">Slack</option></select></label>
            <label>Recipient or channel<input required maxLength={320} value={notificationRecipient} onChange={(event) => setNotificationRecipient(event.target.value)} placeholder="support-ops" /></label>
            <label>Subject (optional)<input maxLength={500} value={notificationSubject} onChange={(event) => setNotificationSubject(event.target.value)} placeholder="Ticket needs review" /></label>
          </div>
          <label>Notification message<textarea required maxLength={10000} rows={3} value={notificationBody} onChange={(event) => setNotificationBody(event.target.value)} placeholder="A bounded update for the configured technician channel" /></label>
          <button type="submit" disabled={notificationBusy || !canWriteExternally || !selectedClientId || !notificationRecipient.trim() || !notificationBody.trim()} title={!selectedClientId ? "Select a client from the top bar first" : !canWriteExternally ? "External writes are disabled in Safe Mode" : undefined}>{notificationBusy ? "Preparing…" : "Prepare notification approval"}</button>
        </form>
        <section className="notification-activity" aria-labelledby="notification-activity-heading">
          <div className="panel-heading">
            <div><h3 id="notification-activity-heading">Notification activity</h3><p className="screen-note">Tenant-scoped request status, approval linkage, and redacted delivery evidence.</p></div>
            <button className="secondary-button" type="button" onClick={() => void refreshNotificationRuns()} disabled={notificationLoading}>{notificationLoading ? "Loading…" : "Refresh activity"}</button>
          </div>
          {notificationError ? <div className="notice danger" role="alert">{notificationError}</div> : null}
          {notificationRuns.length === 0 && !notificationLoading ? <p>No notification requests yet.</p> : null}
          {notificationRuns.length > 0 ? <ul className="notification-activity-list">
            {notificationRuns.map((run) => {
              const channel = typeof run.output?.channel === "string" ? run.output.channel : "notification";
              const providerStatus = typeof run.output?.provider_status === "string" ? run.output.provider_status : "";
              const receiptId = typeof run.output?.receipt_id === "string" ? run.output.receipt_id : "";
              const detail = run.error_detail || providerStatus || (run.approval_id ? `approval ${run.approval_id} pending` : "No delivery detail recorded.");
              return <li key={run.id}>
                <div><strong>{channel}</strong><span>{run.status}</span></div>
                <small>{detail}</small>
                {receiptId ? <small>Receipt recorded: {receiptId}</small> : null}
              </li>;
            })}
          </ul> : null}
        </section>
      </section>

      <div className="technician-chat-layout">
        <section className="panel technician-session-list">
          <div className="panel-heading"><h3>Sessions</h3><span>{loading ? "Loading…" : sessions.length}</span></div>
          {sessions.length === 0 && !loading ? <p>No technician sessions yet.</p> : null}
          {sessions.map((session) => <button key={session.id} className={`technician-session ${activeSession?.id === session.id ? "selected" : ""}`} type="button" onClick={() => void openSession(session.id)}><strong>{session.id}</strong><span>{session.ticket_id || "No ticket selected"}</span><em>{session.status}</em></button>)}
        </section>

        <section className="panel technician-conversation">
          {activeSession ? <>
            <div className="panel-heading"><div><h3>{activeSession.id}</h3><span>{activeSession.client_id}{activeSession.ticket_id ? ` · ${activeSession.ticket_id}` : ""}</span></div><button className="icon-button" type="button" disabled={busy !== null || loadingSession !== null || activeSession.status === "closed"} onClick={() => void closeSession()}>{busy === "close" ? "Closing…" : "Close session"}</button></div>
            <div className="technician-messages" aria-live="polite">{activeSession.messages.length === 0 ? <p>No messages yet. Ask for help, triage, or a bounded ticket action.</p> : activeSession.messages.map((item) => <article key={item.id} className={`technician-message ${item.role}`}><strong>{item.role === "user" ? "You" : "WAIT"}</strong><p>{item.message}</p><small>{item.status}{item.action_id ? ` · ${item.action_id}` : ""}</small></article>)}</div>
            <form className="technician-composer" onSubmit={(event) => void sendMessage(event)}><label className="sr-only" htmlFor="technician-message">Message</label><textarea id="technician-message" required maxLength={2000} rows={3} value={draft} onChange={(event) => setDraft(event.target.value)} disabled={busy !== null || loadingSession !== null || activeSession.status === "closed"} placeholder="Triage TCK-1001, plan a fix for TCK-1001, or type help" /><button type="submit" disabled={busy !== null || loadingSession !== null || !draft.trim() || activeSession.status === "closed"}><Send size={17} aria-hidden="true" />{busy === "send" ? "Sending…" : "Send"}</button></form>
          </> : <div className="empty-state"><MessageSquare size={28} aria-hidden="true" /><h3>Select or start a session</h3><p>Every message stays within the existing technician session scope.</p></div>}
        </section>
      </div>
    </div>
  );
}
