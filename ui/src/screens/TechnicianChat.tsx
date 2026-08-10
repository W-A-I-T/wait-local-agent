import { FormEvent, useCallback, useEffect, useState } from "react";
import { CheckCircle2, MessageSquare, Plus, Send, XCircle } from "lucide-react";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import type { TechnicianChatResponse, TechnicianChatSession } from "../api/types";

export function TechnicianChat() {
  const { canWrite } = useDashboard();
  const [sessions, setSessions] = useState<TechnicianChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<TechnicianChatSession | null>(null);
  const [clientId, setClientId] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState("");
  const [plan, setPlan] = useState<TechnicianChatResponse["plan"] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingSession, setLoadingSession] = useState<string | null>(null);
  const [busy, setBusy] = useState<"create" | "send" | "close" | null>(null);

  const refreshSessions = useCallback(async () => {
    if (!canWrite) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const rows = await apiFetch<TechnicianChatSession[]>("/technician/chat/sessions");
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
  }, [canWrite]);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

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
    setBusy("create");
    setError("");
    setMessage("");
    setPlan(null);
    try {
      const session = await apiFetch<TechnicianChatSession>("/technician/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId.trim() || undefined,
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
            <label>Client id (optional for a scoped technician token)<input value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder="acme" /></label>
            <label>Ticket id (optional)<input value={ticketId} onChange={(event) => setTicketId(event.target.value)} placeholder="TCK-1001" /></label>
          </div>
          <button type="submit" disabled={busy !== null}><Plus size={17} aria-hidden="true" />{busy === "create" ? "Starting…" : "New chat session"}</button>
        </form>
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
