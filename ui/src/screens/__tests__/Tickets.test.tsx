import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiFetch } from "../../api/client";
import { Tickets } from "../Tickets";

vi.mock("../../api/client", () => ({
  apiFetch: vi.fn(),
  ApiRequestError: class ApiRequestError extends Error {
    status?: number;
    constructor(message: string, _technicalDetail?: string, status?: number) { super(message); this.status = status; }
  }
}));

const selectTicket = vi.fn();
let mockRefreshNonce = 0;
let mockSelectedTicketId = "T-1";
vi.mock("../../app/DashboardContext", () => ({
  defaultFieldText: "note=Reviewed by WAIT Local Agent",
  useDashboard: () => ({
    selectedClientId: "acme",
    clients: [{ client_id: "acme", name: "Acme", status: "active" }],
    selectedTicketId: mockSelectedTicketId,
    selectTicket,
    actionTypes: ["add_note"],
    canWrite: false,
    busyId: null,
    createDraft: vi.fn(),
    refreshNonce: mockRefreshNonce
  })
}));

const mockedApiFetch = vi.mocked(apiFetch);

function callsFor(pathSuffix: string) {
  return mockedApiFetch.mock.calls.filter(([path]) => String(path).endsWith(pathSuffix)).length;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

const summaryPayload = { ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] };

describe("Tickets workspace", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    selectTicket.mockReset();
    mockRefreshNonce = 0;
    mockSelectedTicketId = "T-1";
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", client_id: "acme", subject: "Cannot sign in", status: "open", priority: "high", source_system: "connectwise", external_id: "CW-9" }]) as ReturnType<typeof apiFetch>;
      if (path === "/tickets/T-1/summary") return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
  });

  it("renders the client-scoped canonical list and selects a ticket", async () => {
    render(<Tickets />);
    expect(await screen.findByRole("button", { name: "Cannot sign in" })).toBeInTheDocument();
    expect(screen.getByText("connectwise")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cannot sign in" }));
    expect(selectTicket).toHaveBeenCalledWith("T-1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/tickets?client_id=acme");
  });

  it("fetches and renders each detail tab", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/notes")) return Promise.resolve([{ id: 1, ticket_id: "T-1", author: "Ava", body: "Checked logs", created_at: "2026-08-17" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/status-history")) return Promise.resolve([{ id: 2, from_status: "new", to_status: "open", actor: "Ava", created_at: "2026-08-17" }]) as ReturnType<typeof apiFetch>;
      return Promise.resolve({ refs: [{ entity_type: "device", external_id: "D-1" }], links: [{ link_type: "owns_device", from: "user-1", to: "D-1" }] }) as ReturnType<typeof apiFetch>;
    });
    render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    expect(await screen.findByText("Checked logs")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Status History" }));
    expect(await screen.findByText(/new → open/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Context" }));
    expect(await screen.findByText("owns_device")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/tickets/T-1/notes");
    expect(mockedApiFetch).toHaveBeenCalledWith("/tickets/T-1/status-history");
    expect(mockedApiFetch).toHaveBeenCalledWith("/tickets/T-1/context");
  });

  it("shows an empty context state for a 404", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/context")) return Promise.reject(new ApiRequestError("Not found", "Not found", 404));
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Context" }));
    expect(await screen.findByText("No linked context yet.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reuses cached tab data when switching back to a loaded tab", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/notes")) return Promise.resolve([{ id: 1, ticket_id: "T-1", author: "Ava", body: "Checked logs", created_at: "2026-08-17" }]) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await screen.findByText("Checked logs");
    fireEvent.click(screen.getByRole("tab", { name: "Summary" }));
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await screen.findByText("Checked logs");
    expect(callsFor("/tickets/T-1/summary")).toBe(1);
    expect(callsFor("/tickets/T-1/notes")).toBe(1);
  });

  it("refetches the active tab when the Refresh button is clicked", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/notes")) return Promise.resolve([{ id: 1, ticket_id: "T-1", author: "Ava", body: "Checked logs", created_at: "2026-08-17" }]) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await screen.findByText("Checked logs");
    expect(callsFor("/tickets/T-1/notes")).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh Notes" }));
    await waitFor(() => expect(callsFor("/tickets/T-1/notes")).toBe(2));
    expect(callsFor("/tickets/T-1/summary")).toBe(1);
  });

  it("does not re-request the Context tab after a cached 404", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/context")) return Promise.reject(new ApiRequestError("Not found", "Not found", 404));
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Context" }));
    await screen.findByText("No linked context yet.");
    fireEvent.click(screen.getByRole("tab", { name: "Summary" }));
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Context" }));
    await screen.findByText("No linked context yet.");
    expect(callsFor("/tickets/T-1/context")).toBe(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retries a tab that failed with a transient error on the next visit", async () => {
    let notesFail = true;
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/notes")) {
        if (notesFail) return Promise.reject(new Error("Connection lost"));
        return Promise.resolve([{ id: 1, ticket_id: "T-1", author: "Ava", body: "Checked logs", created_at: "2026-08-17" }]) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
    fireEvent.click(screen.getByRole("tab", { name: "Summary" }));
    await screen.findByText("Login issue");
    notesFail = false;
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await screen.findByText("Checked logs");
    expect(callsFor("/tickets/T-1/notes")).toBe(2);
  });

  it("invalidates the cache and refetches the active tab on a global refresh", async () => {
    const { rerender } = render(<Tickets />);
    await screen.findByText("Login issue");
    expect(callsFor("/tickets/T-1/summary")).toBe(1);
    mockRefreshNonce = 1;
    rerender(<Tickets />);
    await waitFor(() => expect(callsFor("/tickets/T-1/summary")).toBe(2));
  });

  it("clears the cache and fetches fresh data when the ticket changes", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve({ ticket_id: "T-1", classification: "Access", summary: "Login issue", suggested_response: "Reset access", sources: [] }) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    const { rerender } = render(<Tickets />);
    await screen.findByText("Login issue");
    expect(callsFor("/tickets/T-1/summary")).toBe(1);
    mockSelectedTicketId = "T-2";
    rerender(<Tickets />);
    await waitFor(() => expect(callsFor("/tickets/T-2/summary")).toBe(1));
    mockSelectedTicketId = "T-1";
    rerender(<Tickets />);
    await waitFor(() => expect(callsFor("/tickets/T-1/summary")).toBe(2));
  });

  it("invalidates the whole cache and discards pre-refresh responses when a global refresh lands mid-load", async () => {
    const staleNotes = deferred<unknown>();
    const freshNotes = deferred<unknown>();
    let notesCalls = 0;
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve(summaryPayload) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/notes")) {
        notesCalls += 1;
        return (notesCalls === 1 ? staleNotes.promise : freshNotes.promise) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    const { rerender } = render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await waitFor(() => expect(callsFor("/tickets/T-1/notes")).toBe(1));
    // Global refresh lands while the Notes load is still in flight and the
    // Summary tab is already cached.
    mockRefreshNonce = 1;
    rerender(<Tickets />);
    await waitFor(() => expect(callsFor("/tickets/T-1/notes")).toBe(2));
    // The response for the request started before the refresh is discarded.
    await act(async () => {
      staleNotes.resolve([{ id: 1, ticket_id: "T-1", author: "Ava", body: "Stale notes", created_at: "2026-08-17" }]);
    });
    expect(screen.queryByText("Stale notes")).not.toBeInTheDocument();
    await act(async () => {
      freshNotes.resolve([{ id: 2, ticket_id: "T-1", author: "Ava", body: "Fresh notes", created_at: "2026-08-17" }]);
    });
    await screen.findByText("Fresh notes");
    // The sibling Summary cache entry was invalidated too.
    fireEvent.click(screen.getByRole("tab", { name: "Summary" }));
    await screen.findByText("Login issue");
    expect(callsFor("/tickets/T-1/summary")).toBe(2);
  });

  it("supersedes an in-flight forced reload when a second global refresh arrives", async () => {
    const firstRefresh = deferred<unknown>();
    const secondRefresh = deferred<unknown>();
    let summaryCalls = 0;
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) {
        summaryCalls += 1;
        if (summaryCalls === 1) return Promise.resolve(summaryPayload) as ReturnType<typeof apiFetch>;
        return (summaryCalls === 2 ? firstRefresh.promise : secondRefresh.promise) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    const { rerender } = render(<Tickets />);
    await screen.findByText("Login issue");
    expect(callsFor("/tickets/T-1/summary")).toBe(1);
    // First global refresh starts a forced reload that stays in flight.
    mockRefreshNonce = 1;
    rerender(<Tickets />);
    await waitFor(() => expect(callsFor("/tickets/T-1/summary")).toBe(2));
    // Second global refresh arrives while the first reload is still pending.
    mockRefreshNonce = 2;
    rerender(<Tickets />);
    await waitFor(() => expect(callsFor("/tickets/T-1/summary")).toBe(3));
    // The first refresh's response is superseded: never rendered or cached.
    await act(async () => {
      firstRefresh.resolve({ ...summaryPayload, summary: "First refresh summary" });
    });
    expect(screen.queryByText("First refresh summary")).not.toBeInTheDocument();
    await act(async () => {
      secondRefresh.resolve({ ...summaryPayload, summary: "Second refresh summary" });
    });
    await screen.findByText("Second refresh summary");
    // The second refresh's response is cached: leaving and returning does not refetch.
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await waitFor(() => expect(callsFor("/tickets/T-1/notes")).toBe(1));
    fireEvent.click(screen.getByRole("tab", { name: "Summary" }));
    await screen.findByText("Second refresh summary");
    expect(callsFor("/tickets/T-1/summary")).toBe(3);
  });

  it("evicts the cached entry when a forced refresh fails so the next visit retries", async () => {
    let notesFail = false;
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }]) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/summary")) return Promise.resolve(summaryPayload) as ReturnType<typeof apiFetch>;
      if (path.endsWith("/notes")) {
        if (notesFail) return Promise.reject(new Error("Connection lost")) as ReturnType<typeof apiFetch>;
        return Promise.resolve([{ id: 1, ticket_id: "T-1", author: "Ava", body: "Checked logs", created_at: "2026-08-17" }]) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    render(<Tickets />);
    await screen.findByText("Login issue");
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await screen.findByText("Checked logs");
    expect(callsFor("/tickets/T-1/notes")).toBe(1);
    notesFail = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh Notes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
    expect(callsFor("/tickets/T-1/notes")).toBe(2);
    // Leaving and returning must retry, not serve the pre-refresh cache entry.
    fireEvent.click(screen.getByRole("tab", { name: "Summary" }));
    await screen.findByText("Login issue");
    notesFail = false;
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    await screen.findByText("Checked logs");
    expect(callsFor("/tickets/T-1/notes")).toBe(3);
  });

  it("discards a late response for a previously selected ticket", async () => {
    const staleSummary = deferred<unknown>();
    let t1SummaryCalls = 0;
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/tickets?client_id=acme") return Promise.resolve([{ id: "T-1", subject: "Cannot sign in" }, { id: "T-2", subject: "Printer jam" }]) as ReturnType<typeof apiFetch>;
      if (path === "/tickets/T-1/summary") {
        t1SummaryCalls += 1;
        return (t1SummaryCalls === 1 ? staleSummary.promise : Promise.resolve(summaryPayload)) as ReturnType<typeof apiFetch>;
      }
      if (path === "/tickets/T-2/summary") return Promise.resolve({ ticket_id: "T-2", classification: "Hardware", summary: "Printer broken", suggested_response: "Replace rollers", sources: [] }) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });
    const { rerender } = render(<Tickets />);
    await screen.findByRole("button", { name: "Cannot sign in" });
    await waitFor(() => expect(callsFor("/tickets/T-1/summary")).toBe(1));
    // Switch tickets while T-1's summary request is still pending.
    mockSelectedTicketId = "T-2";
    rerender(<Tickets />);
    await screen.findByText("Printer broken");
    // T-1's late response must not overwrite T-2's state or cache.
    await act(async () => {
      staleSummary.resolve(summaryPayload);
    });
    expect(screen.queryByText("Login issue")).not.toBeInTheDocument();
    expect(screen.getByText("Printer broken")).toBeInTheDocument();
    // Returning to T-1 fetches fresh because the late response was never cached.
    mockSelectedTicketId = "T-1";
    rerender(<Tickets />);
    await screen.findByText("Login issue");
    expect(callsFor("/tickets/T-1/summary")).toBe(2);
  });
});
