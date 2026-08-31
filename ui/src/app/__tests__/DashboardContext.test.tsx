import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardProvider, getWriteHealthPosture, useDashboard } from "../DashboardContext";
import { apiFetch } from "../../api/client";

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
  const {
    capabilityError,
    capabilityGrants,
    capabilityResolved,
    clientId,
    clients,
    endUserSupportEnabled,
    authState,
    isAdmin,
    refresh,
    roleResolved,
    selectedClientId,
    setSelectedClientId
  } = useDashboard();
  return (
    <>
      <button type="button" onClick={() => void refresh()}>Refresh credentials</button>
      <button type="button" onClick={() => setSelectedClientId("client-a")}>Select client A</button>
      <output>{roleResolved ? "access resolved" : "access unresolved"}</output>
      <output data-testid="auth-state">{authState ?? "unresolved"}</output>
      <output data-testid="legacy-client-id">{clientId}</output>
      <output data-testid="end-user-support-enabled">{endUserSupportEnabled ? "enabled" : "disabled"}</output>
      <output data-testid="selected-client-id">{selectedClientId}</output>
      <output data-testid="client-directory">{clients.map((client) => client.client_id).join(",")}</output>
      <output data-testid="capability-resolved">{capabilityResolved ? "capabilities resolved" : "capabilities unresolved"}</output>
      <output data-testid="capability-grants">{capabilityGrants.map((grant) => `${grant.capability_key}:${grant.client_id ?? "global"}`).join(",")}</output>
      <output data-testid="capability-error">{capabilityError}</output>
      {isAdmin ? <button type="button">Admin controls</button> : null}
    </>
  );
}

describe("DashboardContext role refresh", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedApiFetch.mockReset();
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        throw new Error("A role response must be queued by the test.");
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });
  });

  it.each([
    ["local-open", { role: "admin", api_auth_required: false, demo_mode: false }, ""],
    ["demo", { role: "viewer", api_auth_required: true, demo_mode: true }, ""],
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

function defaultResponse(path: string): unknown {
  if (path === "/connectors/halopsa/tickets") {
    return { result: { status: "blocked", message: "Tickets unavailable.", count: 0 }, items: [] };
  }
  if (path === "/connectors/halopsa/write-health") {
    return { status: "blocked", message: "Write health unavailable.", count: 0 };
  }
  if (path === "/packs/microsoft-admin/access/effective") {
    return { principal_id: null, supported_capabilities: [], grants: [] };
  }
  return [];
}
