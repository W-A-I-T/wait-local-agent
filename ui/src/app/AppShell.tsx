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
    roleResolved,
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
            <h1>WAIT AI Solutions Architect</h1>
            <p>Local-first solution design, governed execution, and MSP operations.</p>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" type="button" onClick={() => void refresh()}>
              <RefreshCw size={17} aria-hidden="true" />
              Refresh
            </button>
            <form className="token-form" onSubmit={(event) => {
              event.preventDefault();
              void saveApiToken();
            }}>
              <input
                aria-hidden="true"
                autoComplete="username"
                className="sr-only"
                name="username"
                readOnly
                tabIndex={-1}
                value="local-appliance"
                onChange={() => undefined}
              />
              <label className="token-input">
                <span className="sr-only">API token</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder="Bearer token"
                  value={apiToken}
                  onChange={(event) => setApiToken(event.target.value)}
                />
              </label>
              <button className="icon-button" type="submit">
                <KeyRound size={17} aria-hidden="true" />
                Save Token
              </button>
            </form>
            <button className="icon-button" type="button" onClick={() => void clearApiToken()}>
              Clear Token
            </button>
            <div className="status-pill">Role: {roleResolved ? role : "checking access"}</div>
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
