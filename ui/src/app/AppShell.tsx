import { AlertTriangle, CheckCircle2, KeyRound, RefreshCw, XCircle } from "lucide-react";
import { useDashboard } from "./DashboardContext";
import { Sidebar } from "./Sidebar";
import { AppRoutes } from "../routes";

export function AppShell() {
  const {
    apiToken,
    setApiToken,
    saveApiToken,
    clearApiToken,
    refresh,
    role,
    writeHealth,
    liveWritesReady,
    statusMessage,
    refreshErrors
  } = useDashboard();

  return (
    <main className="shell">
      <Sidebar />
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
            <label className="token-input">
              <span className="sr-only">API token</span>
              <input
                type="password"
                placeholder="Bearer token"
                value={apiToken}
                onChange={(event) => setApiToken(event.target.value)}
              />
            </label>
            <button className="icon-button" type="button" onClick={() => void saveApiToken()}>
              <KeyRound size={17} aria-hidden="true" />
              Save Token
            </button>
            <button className="icon-button" type="button" onClick={() => void clearApiToken()}>
              Clear Token
            </button>
            <div className="status-pill">Role: {role}</div>
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
        {refreshErrors.length > 0 ? (
          <div className="notice danger" role="alert">
            <AlertTriangle size={17} aria-hidden="true" />
            {refreshErrors.join(" ")}
          </div>
        ) : null}

        <AppRoutes />
      </section>
    </main>
  );
}
