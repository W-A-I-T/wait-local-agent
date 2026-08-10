import { FormEvent, type CSSProperties, useState } from "react";
import { AlertTriangle, CheckCircle2, KeyRound, LifeBuoy, Search, ShieldCheck } from "lucide-react";
import { apiFetch, ApiRequestError } from "../api/client";
import type { EndUserBranding, EndUserMessage, EndUserTicket } from "../api/types";

const tokenStorageKey = "wait-local-agent-end-user-token";
const defaultBranding: EndUserBranding = {
  brand_name: "WAIT Support",
  brand_tagline: "Private help desk",
  brand_logo_data_uri: "",
  brand_accent_color: "#1f6f55",
  brand_surface_color: "#f3f5f2"
};

function loadToken(): string {
  try {
    return window.localStorage.getItem(tokenStorageKey) ?? "";
  } catch {
    return "";
  }
}

function endUserFetch<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token.trim()) {
    headers.set("Authorization", `Bearer ${token.trim()}`);
  } else {
    // Override the operator token that apiFetch may otherwise load from its
    // dashboard storage. End-user requests must never fall back to it.
    headers.set("Authorization", "");
  }
  return apiFetch<T>(path, { ...init, headers });
}

export function EndUserSupport() {
  const [token, setToken] = useState(loadToken);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [lookupId, setLookupId] = useState("");
  const [ticket, setTicket] = useState<EndUserTicket | null>(null);
  const [messages, setMessages] = useState<EndUserMessage[]>([]);
  const [replyBody, setReplyBody] = useState("");
  const [branding, setBranding] = useState<EndUserBranding>(defaultBranding);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"create" | "lookup" | "message" | "escalate" | null>(null);

  async function saveToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (token.trim()) {
        window.localStorage.setItem(tokenStorageKey, token.trim());
      } else {
        window.localStorage.removeItem(tokenStorageKey);
      }
    } catch {
      // The token still applies to this page session when storage is unavailable.
    }
    setError("");
    if (!token.trim()) {
      setBranding(defaultBranding);
      setMessage("Access token cleared.");
      return;
    }
    try {
      setBranding(await endUserFetch<EndUserBranding>(token, "/end-user/config"));
      setMessage("Access token saved on this device.");
    } catch (requestError) {
      setMessage("Access token saved. Default support branding is shown.");
      setError(userFacingError(requestError, "We couldn't load your support branding."));
    }
  }

  async function createTicket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) {
      setError("Enter the access token provided by your support team.");
      return;
    }
    setBusy("create");
    setError("");
    setMessage("");
    try {
      const created = await endUserFetch<EndUserTicket>(token, "/end-user/tickets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: subject.trim(), body: body.trim() })
      });
      setTicket(created);
      setMessages([]);
      setLookupId(created.ticket_id);
      setSubject("");
      setBody("");
      setMessage(`Your request ${created.ticket_id} was submitted.`);
    } catch (requestError) {
      setError(userFacingError(requestError, "We couldn't submit your request."));
    } finally {
      setBusy(null);
    }
  }

  async function lookupTicket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticketId = lookupId.trim();
    if (!token.trim()) {
      setError("Enter the access token provided by your support team.");
      return;
    }
    if (!ticketId) {
      setError("Enter the request number first.");
      return;
    }
    setBusy("lookup");
    setError("");
    setMessage("");
    try {
      const [ticketResult, messageResults] = await Promise.all([
        endUserFetch<EndUserTicket>(token, `/end-user/tickets/${encodeURIComponent(ticketId)}`),
        endUserFetch<EndUserMessage[]>(token, `/end-user/tickets/${encodeURIComponent(ticketId)}/messages`)
      ]);
      setTicket(ticketResult);
      setMessages(messageResults);
    } catch (requestError) {
      setTicket(null);
      setError(userFacingError(requestError, "We couldn't find that request."));
    } finally {
      setBusy(null);
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ticket || !token.trim() || !replyBody.trim()) {
      return;
    }
    setBusy("message");
    setError("");
    setMessage("");
    try {
      const created = await endUserFetch<EndUserMessage>(token, `/end-user/tickets/${encodeURIComponent(ticket.ticket_id)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: replyBody.trim() })
      });
      setMessages((current) => [...current, created]);
      setReplyBody("");
      setMessage("Your message was sent to the support team.");
    } catch (requestError) {
      setError(userFacingError(requestError, "We couldn't send your message."));
    } finally {
      setBusy(null);
    }
  }

  async function escalateTicket() {
    if (!ticket || !token.trim()) {
      return;
    }
    setBusy("escalate");
    setError("");
    setMessage("");
    try {
      setTicket(await endUserFetch<EndUserTicket>(token, `/end-user/tickets/${encodeURIComponent(ticket.ticket_id)}/escalate`, { method: "POST" }));
      setMessage("Your request was marked for technician attention.");
    } catch (requestError) {
      setError(userFacingError(requestError, "We couldn't escalate that request."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="end-user-shell" style={{ "--end-user-accent": branding.brand_accent_color, "--end-user-surface": branding.brand_surface_color } as CSSProperties}>
      <div className="end-user-header">
        <div className="end-user-brand">{branding.brand_logo_data_uri ? <img className="end-user-logo" src={branding.brand_logo_data_uri} alt="" /> : <ShieldCheck size={30} aria-hidden="true" />}<div><strong>{branding.brand_name}</strong><span>{branding.brand_tagline}</span></div></div>
        <div className="end-user-secure"><KeyRound size={16} aria-hidden="true" /> Access is limited to your support account</div>
      </div>
      <section className="end-user-intro">
        <p className="eyebrow">CLIENT SUPPORT</p>
        <h1>How can we help?</h1>
        <p>Send a request to your support team or check the progress of an existing request.</p>
      </section>

      {message ? <div className="notice" role="status"><CheckCircle2 size={17} aria-hidden="true" />{message}</div> : null}
      {error ? <div className="notice danger" role="alert"><AlertTriangle size={17} aria-hidden="true" />{error}</div> : null}

      <div className="end-user-grid">
        <section className="panel">
          <div className="panel-heading"><h2>Access</h2><span>Required for private requests</span></div>
          <form className="draft-form" onSubmit={saveToken}>
            <label>Support access token<input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Provided by your support team" /></label>
            <button type="submit" className="icon-button"><KeyRound size={17} aria-hidden="true" />Save access</button>
          </form>
          <p className="screen-note">This token is scoped to your organization and requester identity. It cannot open another customer’s requests.</p>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>New request</h2><LifeBuoy size={20} aria-hidden="true" /></div>
          <form className="draft-form" onSubmit={(event) => void createTicket(event)}>
            <label>Subject<input required maxLength={200} value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="What do you need help with?" /></label>
            <label>Details<textarea required maxLength={10000} rows={6} value={body} onChange={(event) => setBody(event.target.value)} placeholder="Tell us what happened and what you have already tried." /></label>
            <button type="submit" disabled={busy !== null || !token.trim()}>{busy === "create" ? "Submitting…" : "Submit request"}</button>
          </form>
        </section>

        <section className="panel">
          <div className="panel-heading"><h2>Check a request</h2><Search size={20} aria-hidden="true" /></div>
          <form className="draft-form" onSubmit={(event) => void lookupTicket(event)}>
            <label>Request number<input required value={lookupId} onChange={(event) => setLookupId(event.target.value)} placeholder="EUS-..." /></label>
            <button type="submit" disabled={busy !== null || !token.trim()}>{busy === "lookup" ? "Checking…" : "Check status"}</button>
          </form>
          {ticket ? <div className="end-user-ticket" aria-live="polite"><strong>{ticket.ticket_id}</strong><span>{ticket.subject}</span><span>Status: {ticket.status}</span><span>Priority: {ticket.priority}</span><button type="button" disabled={busy !== null || ticket.status === "escalated"} onClick={() => void escalateTicket()}>{busy === "escalate" ? "Escalating…" : ticket.status === "escalated" ? "Already escalated" : "Ask for technician attention"}</button></div> : <p className="screen-note">Your request details will appear here after a successful lookup.</p>}
          {ticket ? <div className="end-user-messages"><strong>Conversation</strong>{messages.length ? messages.map((item) => <p key={item.id}>{item.body}</p>) : <span>No follow-up messages yet.</span>}<form className="draft-form" onSubmit={(event) => void sendMessage(event)}><label>Send a follow-up<textarea required maxLength={10000} rows={3} value={replyBody} onChange={(event) => setReplyBody(event.target.value)} placeholder="Add information for your support team" /></label><button type="submit" disabled={busy !== null || !replyBody.trim()}>{busy === "message" ? "Sending…" : "Send message"}</button></form></div> : null}
        </section>
      </div>
    </main>
  );
}

function userFacingError(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    return error.message;
  }
  return error instanceof Error ? error.message : fallback;
}
