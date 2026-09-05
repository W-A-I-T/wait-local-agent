import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardProvider, getWriteHealthPosture, useDashboard } from "../DashboardContext";
import { apiFetch } from "../../api/client";
import { apiTokenStorageKey, selectedClientStorageKey } from "../../api/headers";

vi.mock("../../api/client", () => ({
  apiFetch: vi.fn()
}));

const mockedApiFetch = vi.mocked(apiFetch);

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function DashboardHarness() {
  const dashboard = useDashboard();
  const {
    capabilityError,
    capabilityGrants,
    capabilityResolved,
    canWrite,
    canWriteExternally,
    clientId,
    clients,
    endUserSupportEnabled,
    authState,
    isAdmin,
    isMspAdmin,
    liveWritesReady,
    refresh,
    refreshConfiguration,
    recheckWriteHealth,
    logout,
    roleResolved,
    selectedClientId,
    setSelectedClientId,
    clientScopeIds,
    writeHealthByConnector
  } = dashboard;
  return (
    <>
      <button type="button" onClick={() => void refresh()}>Refresh credentials</button>
      <button type="button" onClick={() => void logout()}>Sign out</button>
      <button type="button" onClick={() => void refreshConfiguration()}>Refresh configuration</button>
      <button type="button" onClick={() => void recheckWriteHealth()}>Re-check write health</button>
      <button type="button" onClick={() => setSelectedClientId("client-a")}>Select client A</button>
      <output>{roleResolved ? "access resolved" : "access unresolved"}</output>
      <output data-testid="auth-state">{authState ?? "unresolved"}</output>
      <output data-testid="can-write">{canWrite ? "yes" : "no"}</output>
      <output data-testid="can-write-externally">{canWriteExternally ? "yes" : "no"}</output>
      <output data-testid="legacy-client-id">{clientId}</output>
      <output data-testid="end-user-support-enabled">{endUserSupportEnabled ? "enabled" : "disabled"}</output>
      <output data-testid="selected-client-id">{selectedClientId}</output>
      <output data-testid="client-directory">{clients.map((client) => client.client_id).join(",")}</output>
      <output data-testid="capability-resolved">{capabilityResolved ? "capabilities resolved" : "capabilities unresolved"}</output>
      <output data-testid="capability-grants">{capabilityGrants.map((grant) => `${grant.capability_key}:${grant.client_id ?? "global"}`).join(",")}</output>
      <output data-testid="capability-error">{capabilityError}</output>
      <output data-testid="client-scope">{clientScopeIds === null ? "unknown" : clientScopeIds.join(",") || "empty"}</output>
      <output data-testid="msp-admin">{isMspAdmin ? "yes" : "no"}</output>
      <output data-testid="live-writes-ready">{liveWritesReady ? "yes" : "no"}</output>
      <output data-testid="write-health-map">{Object.entries(writeHealthByConnector).map(([id, health]) => `${id}:${health.status}`).join(",")}</output>
      {isAdmin ? <button type="button">Admin controls</button> : null}
    </>
  );
}

describe("DashboardContext role refresh", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    mockedApiFetch.mockReset();
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        throw new Error("A role response must be queued by the test.");
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });
  });

  it.each([
    ["demo", { role: "admin", api_auth_required: false, demo_mode: true }, ""],
    ["authenticated", { role: "viewer", api_auth_required: true, demo_mode: false }, "saved-token"]
  ] as const)("derives the %s auth state from the role response", async (expectedState, response, token) => {
    if (token) {
      window.localStorage.setItem("wait-local-agent-api-token", token);
    }
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve(response) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("auth-state")).toHaveTextContent(expectedState));
  });

  it.each([
    ["admin with writes disabled", { role: "admin", allow_write_actions: false }, "yes"],
    ["end user with writes enabled", { role: "end_user", allow_write_actions: true }, "no"],
    ["technician with writes enabled", { role: "technician", allow_write_actions: true }, "yes"],
  ] as const)("derives canWrite for %s", async (_caseName, response, expected) => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve(response) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("can-write")).toHaveTextContent(expected));
  });

  it("derives canWriteExternally from the role capability and global write flag", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({ role: "admin", allow_write_actions: false }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("can-write")).toHaveTextContent("yes"));
    expect(screen.getByTestId("can-write-externally")).toHaveTextContent("no");
  });

  it("prefers an authenticated browser session and clears a stale bearer token", async () => {
    window.localStorage.setItem("wait-local-agent-api-token", "stale-token");
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/session") {
        return Promise.resolve({
          authenticated: true,
          role: "viewer",
          api_auth_required: true,
          demo_mode: false,
          end_user_support_enabled: false,
          auth_method: "local",
          principal_id: "operator"
        }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("auth-state")).toHaveTextContent("authenticated"));
    expect(mockedApiFetch.mock.calls.some(([path]) => path === "/auth/role")).toBe(false);
    expect(window.localStorage.getItem("wait-local-agent-api-token")).toBeNull();
  });

  it("keeps a stored bearer token when the session probe reports bearer auth", async () => {
    window.localStorage.setItem("wait-local-agent-api-token", "legacy-token");
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/session") {
        return Promise.resolve({
          authenticated: true,
          role: "admin",
          api_auth_required: true,
          demo_mode: false,
          end_user_support_enabled: false,
          auth_method: "bearer"
        }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/auth/role") {
        return Promise.resolve({
          role: "admin",
          api_auth_required: true,
          demo_mode: false,
          end_user_support_enabled: false,
          auth_method: "bearer"
        }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("auth-state")).toHaveTextContent("authenticated"));
    expect(window.localStorage.getItem("wait-local-agent-api-token")).toBe("legacy-token");
    expect(mockedApiFetch.mock.calls.some(([path]) => path === "/auth/role")).toBe(true);
  });

  it("clears a break-glass session token when signing out", async () => {
    window.sessionStorage.setItem(apiTokenStorageKey, "bootstrap-token");
    window.localStorage.setItem(selectedClientStorageKey, "previous-client");
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({ role: "admin", api_auth_required: true, demo_mode: false }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/auth/logout") {
        return Promise.resolve({ authenticated: false }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByText("access resolved")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(window.sessionStorage.getItem(apiTokenStorageKey)).toBeNull());
    expect(window.localStorage.getItem(selectedClientStorageKey)).toBeNull();
    expect(screen.getByTestId("selected-client-id")).toBeEmptyDOMElement();
  });

  it("removes administrator controls while a newly selected client's role is pending", async () => {
    const selectedRole = deferred<{ role: "viewer" }>();
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return (window.localStorage.getItem(selectedClientStorageKey)
          ? selectedRole.promise
          : Promise.resolve({ role: "admin", demo_mode: true })) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });
    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);
    await screen.findByRole("button", { name: "Admin controls" });

    fireEvent.click(screen.getByRole("button", { name: "Select client A" }));
    expect(screen.queryByRole("button", { name: "Admin controls" })).not.toBeInTheDocument();
    expect(screen.getByTestId("can-write")).toHaveTextContent("no");
    expect(screen.getByTestId("capability-grants")).toBeEmptyDOMElement();

    await act(async () => selectedRole.resolve({ role: "viewer" }));
    await screen.findByText("access resolved");
    expect(screen.queryByRole("button", { name: "Admin controls" })).not.toBeInTheDocument();
    expect(screen.getByTestId("can-write")).toHaveTextContent("no");
  });

  it("derives invalid-token only when a saved token receives a 401", async () => {
    window.localStorage.setItem("wait-local-agent-api-token", "saved-token");
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.reject({ status: 401 }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("auth-state")).toHaveTextContent("invalid-token"));
  });

  it("ignores an older admin role response after a newer viewer refresh begins", async () => {
    const olderAdminRole = deferred<{ role: "admin" }>();
    const newerViewerRole = deferred<{ role: "viewer" }>();
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        const roleResponse = mockedApiFetch.mock.calls.filter(([requestPath]) => requestPath === "/auth/role").length === 1
          ? olderAdminRole
          : newerViewerRole;
        return roleResponse.promise as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/auth/role"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh credentials" }));
    await waitFor(() => expect(mockedApiFetch.mock.calls.filter(([path]) => path === "/auth/role")).toHaveLength(2));

    await act(async () => {
      olderAdminRole.resolve({ role: "admin" });
    });

    expect(screen.getByText("access unresolved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Admin controls" })).not.toBeInTheDocument();

    await act(async () => {
      newerViewerRole.resolve({ role: "viewer" });
    });

    await waitFor(() => expect(screen.getByText("access resolved")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Admin controls" })).not.toBeInTheDocument();
  });

  it("keeps the selector separate from clientId, persists scope, and loads capability grants", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({
          role: "admin",
          client_id: "legacy-client",
          api_auth_required: false,
          demo_mode: true
        }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/clients") {
        return Promise.resolve([
          { client_id: "client-a", name: "Client A", status: "active" },
          { client_id: "client-b", name: "Client B", status: "archived" },
          { client_id: "__quarantine__", name: "Quarantine", status: "quarantine" }
        ]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/packs/microsoft-admin/access/effective") {
        return Promise.resolve({
          principal_id: "operator",
          supported_capabilities: ["microsoft_admin"],
          grants: [{ capability_key: "microsoft_admin", client_id: "client-a" }]
        }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("client-directory")).toHaveTextContent("client-a,client-b"));
    expect(screen.getByTestId("legacy-client-id")).toHaveTextContent("legacy-client");
    expect(screen.getByTestId("selected-client-id")).toHaveTextContent("");
    expect(screen.getByTestId("capability-resolved")).toHaveTextContent("capabilities resolved");
    expect(screen.getByTestId("capability-grants")).toHaveTextContent("microsoft_admin:client-a");

    fireEvent.click(screen.getByRole("button", { name: "Select client A" }));

    expect(screen.getByTestId("selected-client-id")).toHaveTextContent("client-a");
    expect(screen.getByTestId("legacy-client-id")).toHaveTextContent("legacy-client");
    expect(window.localStorage.getItem("wait-local-agent-selected-client")).toBe("client-a");
  });

  it("consumes the end-user support flag from the role response", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({
          role: "admin",
          api_auth_required: false,
          demo_mode: true,
          end_user_support_enabled: true
        }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("end-user-support-enabled")).toHaveTextContent("enabled"));
  });

  it("exposes an explicit empty client scope and aggregates every configured PSA health result", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({
          role: "technician",
          client_ids: [],
          api_auth_required: true,
          demo_mode: false,
          auth_method: "local"
        }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connectors") {
        return Promise.resolve([
          { id: "halopsa", name: "HaloPSA", status: "configured", message: "configured" },
          { id: "connectwise", name: "ConnectWise", status: "configured", message: "configured" }
        ]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connectors/halopsa/write-health") {
        return Promise.resolve({ status: "ready", message: "ready", count: 0 }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connectors/connectwise/write-health") {
        return Promise.resolve({ status: "blocked", message: "blocked", count: 0 }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("client-scope")).toHaveTextContent("empty"));
    expect(screen.getByTestId("msp-admin")).toHaveTextContent("no");
    expect(screen.getByTestId("live-writes-ready")).toHaveTextContent("no");
    expect(screen.getByTestId("write-health-map")).toHaveTextContent("halopsa:ready,connectwise:blocked");
  });

  it("caches connector write health for route refreshes and ignores window focus", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({ role: "admin", api_auth_required: false, demo_mode: true }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connectors") {
        return Promise.resolve([
          { id: "halopsa", name: "HaloPSA", status: "configured", message: "configured" },
          { id: "connectwise", name: "ConnectWise", status: "configured", message: "configured" }
        ]) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByText("access resolved")).toBeInTheDocument());
    const healthCallsAfterInitialRefresh = mockedApiFetch.mock.calls.filter(([path]) => path.endsWith("/write-health")).length;

    fireEvent.click(screen.getByRole("button", { name: "Re-check write health" }));
    await waitFor(() => expect(mockedApiFetch.mock.calls.filter(([path]) => path.endsWith("/write-health")).length).toBe(healthCallsAfterInitialRefresh + 2));

    const healthCallsAfterRecheck = mockedApiFetch.mock.calls.filter(([path]) => path.endsWith("/write-health")).length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh configuration" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh configuration" }));
    fireEvent.focus(window);
    await waitFor(() => expect(mockedApiFetch.mock.calls.filter(([path]) => path === "/clients").length).toBeGreaterThan(1));
    expect(mockedApiFetch.mock.calls.filter(([path]) => path.endsWith("/write-health")).length).toBe(healthCallsAfterRecheck);
  });

  it("fails the capability state closed without failing the overall authenticated dashboard refresh", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({
          role: "viewer",
          client_id: "client-a",
          api_auth_required: true,
          demo_mode: false
        }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/packs/microsoft-admin/access/effective") {
        return Promise.reject(new Error("capability service denied")) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByText("access resolved")).toBeInTheDocument());
    expect(screen.getByTestId("capability-resolved")).toHaveTextContent("capabilities resolved");
    expect(screen.getByTestId("capability-grants")).toHaveTextContent("");
    expect(screen.getByTestId("capability-error")).toHaveTextContent("capability service denied");
  });

  it("increments refreshNonce exactly once per refresh call, including on the error path", async () => {
    function NonceHarness() {
      const { refresh, refreshNonce } = useDashboard();
      return (
        <>
          <button type="button" onClick={() => void refresh()}>Refresh nonce</button>
          <output data-testid="refresh-nonce">{refreshNonce}</output>
        </>
      );
    }
    let failRole = false;
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        if (failRole) return Promise.reject(new Error("Auth service down")) as ReturnType<typeof apiFetch>;
        return Promise.resolve({
          role: "admin",
          client_id: "legacy-client",
          api_auth_required: false,
          demo_mode: true
        }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connectors") {
        return Promise.reject(new Error("Connectors down")) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><NonceHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("refresh-nonce")).toHaveTextContent("1"));

    fireEvent.click(screen.getByRole("button", { name: "Refresh nonce" }));
    await waitFor(() => expect(screen.getByTestId("refresh-nonce")).toHaveTextContent("2"));

    failRole = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh nonce" }));
    await waitFor(() => expect(screen.getByTestId("refresh-nonce")).toHaveTextContent("3"));
    await waitFor(() => expect(mockedApiFetch.mock.calls.filter(([path]) => path === "/auth/role")).toHaveLength(3));
    await act(async () => {});
    expect(screen.getByTestId("refresh-nonce")).toHaveTextContent("3");
  });
});

describe("write health posture mapping", () => {
  it("keeps the initial unresolved state quiet", () => {
    expect(getWriteHealthPosture("blocked", false)).toEqual({
      label: "Checking write status…",
      tone: "neutral",
      icon: "info"
    });
  });

  it.each([
    ["blocked", "Safe Mode · writes disabled", "neutral", "info"],
    ["not_configured", "No PSA write path configured", "neutral", "info"],
    ["failed", "Write path error", "warning", "warning"],
    ["ready", "Live writes ready", "success", "success"]
  ] as const)("maps %s to its honest posture", (status, label, tone, icon) => {
    expect(getWriteHealthPosture(status, true)).toEqual({ label, tone, icon });
  });
});

describe("dashboard context cleanup", () => {
  it("does not expose the removed Halo ticket bootstrap", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        return Promise.resolve({ role: "admin", api_auth_required: false, demo_mode: true }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByText("access resolved")).toBeInTheDocument());
    expect(mockedApiFetch.mock.calls.some(([path]) => path === "/connectors/halopsa/tickets")).toBe(false);
  });
});

function defaultResponse(path: string): unknown {
  if (path === "/connectors/halopsa/write-health") {
    return { status: "blocked", message: "Write health unavailable.", count: 0 };
  }
  if (path === "/packs/microsoft-admin/access/effective") {
    return { principal_id: null, supported_capabilities: [], grants: [] };
  }
  return [];
}
