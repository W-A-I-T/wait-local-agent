// SPDX-License-Identifier: AGPL-3.0-only
// Additional terms: ../../../ADDITIONAL_TERMS.md

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Info, KeyRound, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { getWriteHealthPosture, useDashboard, type AuthState } from "./DashboardContext";
import { Sidebar } from "./Sidebar";
import { AppRoutes } from "../routes";
import { WaitAttribution } from "../components/WaitAttribution";

export function AppShell() {
  const {
    apiToken,
    setApiToken,
    saveApiToken,
    clearApiToken,
    refresh,
    role,
    authState,
    roleResolved,
    selectedClientId,
    setSelectedClientId,
    clients,
    writeHealth,
    writeHealthResolved,
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
            <label className="client-selector" htmlFor="app-client-selector">
              <span>Client</span>
              <select
                id="app-client-selector"
                value={selectedClientId}
                onChange={(event) => setSelectedClientId(event.target.value)}
              >
                <option value="">All clients</option>
                {clients.filter((client) => client.status === "active").map((client) => (
                  <option key={client.client_id} value={client.client_id}>{client.name}</option>
                ))}
              </select>
            </label>
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
                <span>API token <small>(optional in local mode)</small></span>
                <input
                  id="app-api-token"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Paste token"
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
            <AuthStatus authState={authState} role={role} roleResolved={roleResolved} />
            <WriteGateStatus writeHealth={writeHealth} resolved={writeHealthResolved} />
          </div>
        </header>

        {statusMessage ? <div className="notice" role="status" aria-live="polite">{statusMessage}</div> : null}
        {refreshErrors.length > 0 ? (
          <div className="notice danger" role="alert">
            <AlertTriangle size={17} aria-hidden="true" />
            {refreshErrors.join(" ")}
          </div>
        ) : null}

        <AppRoutes />
        <WaitAttribution />
      </section>
    </main>
  );
}

export function WriteGateStatus({
  writeHealth,
  resolved
}: {
  writeHealth: { status: string; message: string };
  resolved: boolean;
}) {
  const [open, setOpen] = useState(false);
  const posture = getWriteHealthPosture(writeHealth.status, resolved);
  const Icon = posture.icon === "success"
    ? CheckCircle2
    : posture.icon === "warning"
      ? AlertTriangle
      : Info;
  const explanation = writeHealth.status === "ready"
    ? "Live writes are available because you explicitly enabled the safety gates."
    : "Writes stay disabled until you explicitly enable them.";

  return (
    <div className="write-gate-status">
      <button
        className={`status-pill status-pill-button ${posture.tone}`}
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Icon size={18} aria-hidden="true" />
        {posture.label}
      </button>
      {open ? (
        <div className="auth-help-popover write-gate-popover" role="note">
          <strong>PSA write gate (HaloPSA)</strong>
          <p>{writeHealth.message}</p>
          <p>{explanation}</p>
          <Link to="/connectors">View connector details</Link>
        </div>
      ) : null}
    </div>
  );
}

function AuthStatus({
  authState,
  role,
  roleResolved
}: {
  authState: AuthState | null;
  role: "admin" | "technician" | "viewer";
  roleResolved: boolean;
}) {
  const label = authState === "local-open"
    ? "Local mode · full access"
    : authState === "demo"
      ? "Demo mode"
      : authState === "invalid-token"
        ? "Token rejected"
        : roleResolved
          ? `Role: ${role}`
          : "Checking access";

  return (
    <div className="auth-status">
      <div className={`status-pill ${authState === "invalid-token" ? "danger" : ""}`}>
        {authState === "invalid-token" ? <AlertTriangle size={17} aria-hidden="true" /> : null}
        {label}
      </div>
      {authState ? <AuthHelp authState={authState} /> : null}
    </div>
  );
}

function AuthHelp({ authState }: { authState: AuthState }) {
  const [open, setOpen] = useState(false);
  const title = authState === "local-open"
    ? "Explain local mode"
    : authState === "authenticated"
      ? "Explain authenticated access"
      : authState === "invalid-token"
        ? "Explain rejected token"
        : "Explain demo mode";

  return (
    <div className="auth-help">
      <button
        className="auth-help-button"
        type="button"
        aria-label={title}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Info size={16} aria-hidden="true" />
      </button>
      {open ? <div className="auth-help-popover" role="note">
        {authState === "local-open" ? (
          <>
            <p>The appliance has no API token configured. All requests run as admin in local mode.</p>
            <p>To secure it, set <code>WAIT_ADMIN_TOKEN</code>, <code>WAIT_TECH_TOKEN</code>, or <code>WAIT_VIEWER_TOKEN</code> in the server environment, then paste that token here.</p>
          </>
        ) : null}
        {authState === "authenticated" ? <p>Your role comes from the server&apos;s interpretation of the saved token.</p> : null}
        {authState === "invalid-token" ? <p>The saved token was not accepted. Clear Token resets it.</p> : null}
        {authState === "demo" ? <p>Demo mode is enabled for this appliance. Some write actions are intentionally unavailable.</p> : null}
      </div> : null}
    </div>
  );
}
