import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { type ConnectorStatus } from "../api/types";

type HealthState = {
  status: string;
  message: string;
};

type CompanyRow = { id: string; name: string; archived?: boolean };

type HuduSnapshot = {
  companies: CompanyRow[];
  articles: CompanyRow[];
};

type SyncroComment = {
  id: string;
  ticket_id: string;
  created_at: string;
  updated_at: string;
  subject: string;
  body: string;
  tech: string;
  hidden: boolean;
};

type SyncroCommentsResponse = {
  result: { status: string; message: string; count: number };
  items: SyncroComment[];
  meta: { total_pages?: number; page?: number; per_page?: number };
};

type ScreenConnectActionResponse = {
  status: string;
  approval_id?: number;
  error_detail?: string;
  output?: { message?: string };
};

export function Connectors() {
  const { connectors, haloConnector, huduConnector, writeHealth, loading, canWrite } = useDashboard();
  const [halopsaHealth, setHalopsaHealth] = useState<HealthState | null>(null);
  const [connectwiseHealth, setConnectwiseHealth] = useState<HealthState | null>(null);
  const [connectwiseWriteHealth, setConnectwiseWriteHealth] = useState<HealthState | null>(null);
  const [huduHealth, setHuduHealth] = useState<HealthState | null>(null);
  const [huduData, setHuduData] = useState<HuduSnapshot>({ companies: [], articles: [] });
  const [syncroTicketId, setSyncroTicketId] = useState("");
  const [syncroPage, setSyncroPage] = useState("1");
  const [syncroComments, setSyncroComments] = useState<SyncroComment[]>([]);
  const [syncroMeta, setSyncroMeta] = useState<SyncroCommentsResponse["meta"]>({});
  const [syncroStatus, setSyncroStatus] = useState<HealthState | null>(null);
  const [syncroLoading, setSyncroLoading] = useState(false);
  const [screenConnectClientId, setScreenConnectClientId] = useState("");
  const [screenConnectSessionId, setScreenConnectSessionId] = useState("");
  const [screenConnectNote, setScreenConnectNote] = useState("");
  const [screenConnectHost, setScreenConnectHost] = useState("");
  const [screenConnectMessage, setScreenConnectMessage] = useState("");
  const [screenConnectActionStatus, setScreenConnectActionStatus] = useState<HealthState | null>(null);
  const [screenConnectActionLoading, setScreenConnectActionLoading] = useState(false);

  const refreshConnectivity = useCallback(async () => {
    const results = await Promise.allSettled([
      apiFetch<HealthState>("/connectors/halopsa/health"),
      apiFetch<HealthState>("/connectors/halopsa/write-health"),
      apiFetch<HealthState>("/connectors/connectwise/health"),
      apiFetch<HealthState>("/connectors/connectwise/write-health"),
      apiFetch<HealthState>("/connectors/hudu/health"),
      apiFetch<{ result: { count: number }; items: CompanyRow[] }>("/connectors/hudu/companies"),
      apiFetch<{ result: { count: number }; items: CompanyRow[] }>("/connectors/hudu/articles")
    ]);

    if (results[0].status === "fulfilled") {
      setHalopsaHealth(results[0].value);
    }
    if (results[2].status === "fulfilled") {
      setConnectwiseHealth(results[2].value);
    }
    if (results[3].status === "fulfilled") {
      setConnectwiseWriteHealth(results[3].value);
    }
    if (results[4].status === "fulfilled") {
      setHuduHealth(results[4].value);
    }
    const companiesResult = results[5];
    if (companiesResult.status === "fulfilled") {
      setHuduData((current) => ({
        ...current,
        companies: Array.isArray(companiesResult.value.items)
          ? companiesResult.value.items.slice(0, 8)
          : []
      }));
    }
    const articlesResult = results[6];
    if (articlesResult.status === "fulfilled") {
      setHuduData((current) => ({
        ...current,
        articles: Array.isArray(articlesResult.value.items)
          ? articlesResult.value.items.slice(0, 8)
          : []
      }));
    }
  }, []);

  useEffect(() => {
    void refreshConnectivity();
  }, [refreshConnectivity]);

  const loadSyncroComments = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const ticketId = syncroTicketId.trim();
    const page = Number.parseInt(syncroPage, 10);
    if (!ticketId || !/^[1-9][0-9]{0,18}$/.test(ticketId) || !Number.isInteger(page) || page < 1) {
      setSyncroStatus({ status: "failed", message: "Enter a positive numeric Syncro ticket ID and page." });
      return;
    }
    setSyncroLoading(true);
    setSyncroStatus(null);
    try {
      const response = await apiFetch<SyncroCommentsResponse>(
        `/connectors/syncro/tickets/${encodeURIComponent(ticketId)}/comments?page=${page}&per_page=10`
      );
      setSyncroComments(Array.isArray(response.items) ? response.items : []);
      setSyncroMeta(response.meta ?? {});
      setSyncroStatus(response.result);
    } catch (error) {
      setSyncroComments([]);
      setSyncroMeta({});
      setSyncroStatus({
        status: "failed",
        message: error instanceof Error ? error.message : "Syncro ticket comments could not be loaded."
      });
    } finally {
      setSyncroLoading(false);
    }
  };

  const prepareScreenConnectAction = async (
    event: FormEvent<HTMLFormElement>,
    actionId: "screenconnect-session-note" | "screenconnect-session-message"
  ) => {
    event.preventDefault();
    const clientId = screenConnectClientId.trim();
    const sessionId = screenConnectSessionId.trim();
    const sessionUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!clientId || clientId.length > 200 || !sessionUuid.test(sessionId)) {
      setScreenConnectActionStatus({ status: "failed", message: "Enter a client ID and mapped ScreenConnect session UUID." });
      return;
    }
    const body = actionId === "screenconnect-session-note" ? screenConnectNote.trim() : screenConnectMessage.trim();
    if (!body || body.length > 10000) {
      setScreenConnectActionStatus({ status: "failed", message: "Enter a message of at most 10,000 characters." });
      return;
    }
    if (actionId === "screenconnect-session-message" && (!screenConnectHost.trim() || screenConnectHost.trim().length > 200)) {
      setScreenConnectActionStatus({ status: "failed", message: "Enter the technician display name (at most 200 characters)." });
      return;
    }
    setScreenConnectActionLoading(true);
    setScreenConnectActionStatus(null);
    try {
      const payload = actionId === "screenconnect-session-note"
        ? { session_id: sessionId, note_body: body }
        : { session_id: sessionId, by_host: screenConnectHost.trim(), message: body };
      const response = await apiFetch<ScreenConnectActionResponse>(`/smart-actions/${actionId}/invoke`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId, payload })
      });
      setScreenConnectActionStatus({
        status: response.status,
        message: response.approval_id
          ? `Approval request ${response.approval_id} created. Review it in Approvals before sending.`
          : response.output?.message || response.error_detail || "ScreenConnect action completed."
      });
    } catch (error) {
      setScreenConnectActionStatus({ status: "failed", message: error instanceof Error ? error.message : "ScreenConnect action could not be prepared." });
    } finally {
      setScreenConnectActionLoading(false);
    }
  };

  const rows = connectors.length > 0 ? connectors : [
    { id: "halopsa", name: "HaloPSA", status: "loading", message: "Waiting for connector status" },
    { id: "hudu", name: "Hudu", status: "loading", message: "Waiting for connector status" }
  ];

  function renderConnector(status: ConnectorStatus) {
    return (
      <article className="connector-row" key={status.id}>
        <div>
          <strong>{status.name}</strong>
          <span>{status.message}</span>
        </div>
        <em>{status.status}</em>
      </article>
    );
  }

  return (
    <div className="screen-stack">
      <section className="panel">
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
          <span>Health: {halopsaHealth ? `${halopsaHealth.status} · ${halopsaHealth.message}` : "unknown"}</span>
        </div>
        <div className="connector-summary secondary">
          <div>
            <strong>ConnectWise PSA</strong>
            <span>{connectwiseHealth ? `${connectwiseHealth.status} · ${connectwiseHealth.message}` : "Health unknown."}</span>
          </div>
          <em>{connectwiseWriteHealth?.status || "unknown"}</em>
        </div>
        <div className="flag-grid">
          <span>Ticket updates: {connectwiseWriteHealth?.status === "ready" ? "ready after approval" : "gated"}</span>
          <span>Write health: {connectwiseWriteHealth ? connectwiseWriteHealth.message : "unknown"}</span>
        </div>
        <div className="connector-summary secondary">
          <div>
            <strong>Hudu</strong>
            <span>{huduConnector?.message || "Hudu connector status unavailable."}</span>
          </div>
          <em>{huduConnector?.status || "unknown"}</em>
        </div>
        <div className="flag-grid">
          <span>HTTP probing: {huduConnector?.http_probing_enabled ? "enabled" : "disabled"}</span>
          <span>Companies: {huduData.companies.length}</span>
          <span>Health: {huduHealth ? `${huduHealth.status} · ${huduHealth.message}` : "unknown"}</span>
        </div>
        <button type="button" className="icon-button" onClick={() => void refreshConnectivity()}>Refresh checks</button>
      </section>

      <section className="panel knowledge-panel">
        <div className="panel-heading">
          <h2>Live readout</h2>
          <span>read-only probe snapshot</span>
        </div>
        <div className="table-list">
          {rows.map((row) => renderConnector(row))}
        </div>
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Hudu previews</h2>
          <span>{huduData.companies.length} companies</span>
        </div>
        <div className="table-list">
          {huduData.companies.map((company) => (
            <div className="table-row" key={company.id}>
              <div><strong>{company.name}</strong><span>{company.id}</span></div>
              <em>{company.archived ? "archived" : "active"}</em>
            </div>
          ))}
          {huduData.companies.length === 0 ? <p>No Hudu companies returned.</p> : null}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>ScreenConnect session actions</h2>
          <span>approval required</span>
        </div>
        <p className="screen-note">Prepare a bounded note or message for one locally mapped session. WAIT validates the tenant/session map and places the proposed provider mutation in the approval queue.</p>
        <div className="grid">
          <label>Client ID<input aria-label="ScreenConnect client ID" value={screenConnectClientId} onChange={(event) => setScreenConnectClientId(event.target.value)} placeholder="acme" /></label>
          <label>Session UUID<input aria-label="ScreenConnect session UUID" value={screenConnectSessionId} onChange={(event) => setScreenConnectSessionId(event.target.value)} placeholder="11111111-2222-3333-4444-555555555555" /></label>
        </div>
        <form className="draft-form" onSubmit={(event) => void prepareScreenConnectAction(event, "screenconnect-session-note")}>
          <label>Session note<textarea aria-label="ScreenConnect session note" rows={3} maxLength={10000} value={screenConnectNote} onChange={(event) => setScreenConnectNote(event.target.value)} placeholder="Add an operator note to the mapped session" /></label>
          <button type="submit" disabled={screenConnectActionLoading || !canWrite}>Prepare note approval</button>
        </form>
        <form className="draft-form" onSubmit={(event) => void prepareScreenConnectAction(event, "screenconnect-session-message")}>
          <label>Technician display name<input aria-label="ScreenConnect technician display name" maxLength={200} value={screenConnectHost} onChange={(event) => setScreenConnectHost(event.target.value)} placeholder="WAIT technician" /></label>
          <label>Session message<textarea aria-label="ScreenConnect session message" rows={3} maxLength={10000} value={screenConnectMessage} onChange={(event) => setScreenConnectMessage(event.target.value)} placeholder="Send a bounded message to the mapped session" /></label>
          <button type="submit" disabled={screenConnectActionLoading || !canWrite}>Prepare message approval</button>
        </form>
        {screenConnectActionStatus ? <p className={`screen-note ${screenConnectActionStatus.status === "failed" ? "danger" : ""}`} role="status">{screenConnectActionStatus.message}</p> : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Syncro ticket comments</h2>
          <span>read-only history</span>
        </div>
        <p className="screen-note">Review bounded comment history from the configured Syncro account. This does not post or modify comments.</p>
        <form className="inline-form" onSubmit={(event) => void loadSyncroComments(event)}>
          <label>Ticket ID<input inputMode="numeric" required value={syncroTicketId} onChange={(event) => setSyncroTicketId(event.target.value)} placeholder="42" /></label>
          <label>Page<input type="number" min="1" step="1" required value={syncroPage} onChange={(event) => setSyncroPage(event.target.value)} /></label>
          <button type="submit" disabled={syncroLoading || !syncroTicketId.trim()}>{syncroLoading ? "Loading…" : "Load comments"}</button>
        </form>
        {syncroStatus ? <p className={`screen-note ${syncroStatus.status === "failed" ? "danger" : ""}`} role="status">{syncroStatus.message}</p> : null}
        {syncroComments.length > 0 ? (
          <div className="table-list" aria-label="Syncro ticket comments">
            {syncroComments.map((comment) => (
              <article className="table-row" key={comment.id}>
                <div><strong>{comment.subject || "Comment"}</strong><span>{comment.tech || "Syncro user"} · {comment.created_at || "time unavailable"}</span></div>
                <span>{comment.body}</span>
                <em>{comment.hidden ? "internal" : "customer-visible"}</em>
              </article>
            ))}
          </div>
        ) : syncroStatus?.status === "ready" ? <p>No comments returned for this page.</p> : null}
        {syncroMeta.total_pages && syncroMeta.total_pages > 1 ? <p className="screen-note">Page {syncroMeta.page ?? syncroPage} of {syncroMeta.total_pages}.</p> : null}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Write health detail</h2>
          <span>{writeHealth.status}</span>
        </div>
        <p>{writeHealth.message}</p>
      </section>
    </div>
  );
}
