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
  const { isAdmin, refresh, roleResolved } = useDashboard();
  return (
    <>
      <button type="button" onClick={() => void refresh()}>Refresh credentials</button>
      <output>{roleResolved ? "access resolved" : "access unresolved"}</output>
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
