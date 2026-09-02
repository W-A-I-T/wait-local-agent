// SPDX-License-Identifier: AGPL-3.0-only
// Additional terms: ../../../ADDITIONAL_TERMS.md

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Info, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { getWriteHealthPosture, useDashboard, type AuthState } from "./DashboardContext";
import { Sidebar } from "./Sidebar";
import { AppRoutes } from "../routes";
import { WaitAttribution } from "../components/WaitAttribution";

export function AppShell() {
  const {
    logout,
    refresh,
    role,
    principalId,
    authMethod,
    authState,
    roleResolved,
    selectedClientId,
    setSelectedClientId,
    clients,
    clientScopeIds,
    isMspAdmin,
    writeHealthByConnector,
    connectors,
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
            <div className="account-chip" aria-label="Signed-in account">
              <strong>{principalId ?? (authState === "demo" ? "Demo appliance" : "Local appliance")}</strong>
              <span>{authMethodLabel(authMethod, authState)}</span>
            </div>
            <button className="icon-button" type="button" onClick={() => void logout()}>
              Sign out
            </button>
            <AuthStatus authState={authState} role={role} roleResolved={roleResolved} />
            <WriteGateStatus
              connectors={connectors}
              writeHealthByConnector={writeHealthByConnector}
              resolved={writeHealthResolved}
            />
          </div>
        </header>

        {statusMessage ? <div className="notice" role="status" aria-live="polite">{statusMessage}</div> : null}
        {roleResolved && !isMspAdmin && clientScopeIds?.length === 0 ? (
          <div className="notice" role="status">
            Your access has no client scope yet. Ask an administrator to assign you to a client.
          </div>
        ) : null}
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

function authMethodLabel(authMethod: string, authState: AuthState | null): string {
  if (authState === "demo") {
    return "Demo access";
  }
  if (authMethod === "local") {
    return "Browser session";
  }
  if (authMethod === "bearer") {
    return "API token";
  }
  return authMethod;
}

export function WriteGateStatus({
  connectors,
  writeHealthByConnector,
  resolved
}: {
  connectors: Array<{ id: string; name: string; status: string }>;
  writeHealthByConnector: Record<string, { status: string; message: string }>;
  resolved: boolean;
}) {
  const [open, setOpen] = useState(false);
  const psaConnectors = connectors.filter((connector) =>
    ["halopsa", "connectwise", "servicenow", "autotask"].includes(connector.id)
    && connector.status !== "not_configured"
  );
  const posture = getAggregateWriteHealthPosture(psaConnectors, writeHealthByConnector, resolved);
  const Icon = posture.icon === "success"
    ? CheckCircle2
    : posture.icon === "warning"
      ? AlertTriangle
      : Info;
  const explanation = posture.label === "Live writes ready"
    ? "Live writes are available because you explicitly enabled the safety gates."
    : posture.label === "No PSA connected"
      ? "Connect a PSA to enable governed live writes."
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
          <strong>PSA write gates</strong>
          {psaConnectors.length > 0 ? (
            <ul>
              {psaConnectors.map((connector) => {
                const health = writeHealthByConnector[connector.id] ?? { status: "failed", message: "Unable to verify this PSA write path." };
                return (
                  <li key={connector.id}>
                    <strong>{connector.name}</strong>: {getWriteHealthPosture(health.status, resolved).label}
                    <p>{health.message}</p>
                  </li>
                );
              })}
            </ul>
          ) : <p>No PSA connector is configured.</p>}
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
  const label = authState === "demo"
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
  const title = authState === "authenticated"
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
        {authState === "authenticated" ? <p>Your access level comes from your signed-in account.</p> : null}
        {authState === "invalid-token" ? <p>Your saved access credential was not accepted. Sign in again.</p> : null}
        {authState === "demo" ? <p>Demo mode is enabled for this appliance. Some write actions are intentionally unavailable.</p> : null}
      </div> : null}
    </div>
  );
}

function getAggregateWriteHealthPosture(
  connectors: Array<{ id: string; name: string; status: string }>,
  healthByConnector: Record<string, { status: string; message: string }>,
  resolved: boolean
) {
  if (!resolved) {
    return getWriteHealthPosture(null, false);
  }
  if (connectors.length === 0) {
    return { label: "No PSA connected", tone: "neutral" as const, icon: "info" as const };
  }
  const statuses = connectors.map((connector) => healthByConnector[connector.id]?.status ?? "failed");
  if (statuses.includes("failed")) {
    return getWriteHealthPosture("failed", true);
  }
  if (statuses.includes("blocked")) {
    return getWriteHealthPosture("blocked", true);
  }
  if (statuses.every((status) => status === "ready")) {
    return getWriteHealthPosture("ready", true);
  }
  return getWriteHealthPosture("failed", true);
}
