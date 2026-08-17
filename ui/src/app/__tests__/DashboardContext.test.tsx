import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardProvider, useDashboard } from "../DashboardContext";
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
  const { clientId, clients, isAdmin, refresh, roleResolved, selectedClientId, setSelectedClientId } = useDashboard();
  return (
    <>
      <button type="button" onClick={() => void refresh()}>Refresh credentials</button>
      <button type="button" onClick={() => setSelectedClientId("client-a")}>Select client A</button>
      <output>{roleResolved ? "access resolved" : "access unresolved"}</output>
      <output data-testid="legacy-client-id">{clientId}</output>
      <output data-testid="selected-client-id">{selectedClientId}</output>
      <output data-testid="client-directory">{clients.map((client) => client.client_id).join(",")}</output>
      {isAdmin ? <button type="button">Admin controls</button> : null}
    </>
  );
}

describe("DashboardContext role refresh", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/auth/role") {
        throw new Error("A role response must be queued by the test.");
      }
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });
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

  it("keeps the selector separate from clientId and populates client options", async () => {
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
      return Promise.resolve(defaultResponse(path)) as ReturnType<typeof apiFetch>;
    });

    render(<DashboardProvider><DashboardHarness /></DashboardProvider>);

    await waitFor(() => expect(screen.getByTestId("client-directory")).toHaveTextContent("client-a,client-b"));
    expect(screen.getByTestId("legacy-client-id")).toHaveTextContent("legacy-client");
    expect(screen.getByTestId("selected-client-id")).toHaveTextContent("");

    fireEvent.click(screen.getByRole("button", { name: "Select client A" }));

    expect(screen.getByTestId("selected-client-id")).toHaveTextContent("client-a");
    expect(screen.getByTestId("legacy-client-id")).toHaveTextContent("legacy-client");
  });
});

function defaultResponse(path: string): unknown {
  if (path === "/connectors/halopsa/tickets") {
    return { result: { status: "blocked", message: "Tickets unavailable.", count: 0 }, items: [] };
  }
  if (path === "/connectors/halopsa/write-health") {
    return { status: "blocked", message: "Write health unavailable.", count: 0 };
  }
  return [];
}
