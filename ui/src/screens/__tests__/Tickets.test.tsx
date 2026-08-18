import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
vi.mock("../../app/DashboardContext", () => ({
  defaultFieldText: "note=Reviewed by WAIT Local Agent",
  useDashboard: () => ({
    selectedClientId: "acme",
    clients: [{ client_id: "acme", name: "Acme", status: "active" }],
    selectedTicketId: "T-1",
    selectTicket,
    actionTypes: ["add_note"],
    canWrite: false,
    busyId: null,
    createDraft: vi.fn()
  })
}));

const mockedApiFetch = vi.mocked(apiFetch);

describe("Tickets workspace", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    selectTicket.mockReset();
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
});
