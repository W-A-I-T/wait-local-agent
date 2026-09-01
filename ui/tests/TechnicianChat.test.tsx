import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TechnicianChat } from "../src/screens/TechnicianChat";

const dashboard = vi.hoisted(() => ({
  canWrite: true,
  clients: [{ client_id: "acme", name: "Acme Support", status: "active" }]
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

const session = {
  id: "TCS-1",
  status: "active",
  ticket_id: "TCK-1001",
  client_id: "acme",
  created_at: "2026-08-09T00:00:00Z",
  updated_at: "2026-08-09T00:00:00Z",
  messages: []
};

describe("TechnicianChat", () => {
  beforeEach(() => {
    dashboard.canWrite = true;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/technician/chat/sessions" && !init?.method) {
        return Promise.resolve(json([session]));
      }
      if (path === "/smart-actions/runs" && !init?.method) {
        return Promise.resolve(json([{
          id: 8,
          action_id: "communication-send",
          actor: "tech-1",
          status: "failed",
          approval_id: null,
          output: { channel: "teams" },
          evidence: [],
          error_detail: "communication delivery is not configured",
          created_at: "2026-08-09T00:00:00Z",
          updated_at: "2026-08-09T00:00:00Z",
          client_id: "acme"
        }]));
      }
      if (path === "/technician/chat/sessions/TCS-1" && !init?.method) {
        return Promise.resolve(json({ ...session, messages: [{ id: 1, role: "assistant", message: "Ready.", status: "help", action_id: null, ticket_id: "TCK-1001", created_at: "2026-08-09T00:00:00Z" }] }));
      }
      if (path === "/technician/chat/sessions" && init?.method === "POST") {
        return Promise.resolve(json({ ...session, id: "TCS-2", messages: [] }));
      }
      if (path === "/technician/chat/sessions/TCS-1/messages") {
        return Promise.resolve(json({ status: "success", message: "I prepared a bounded ticket summary.", session_id: "TCS-1", action_id: "ticket-summary", result: { status: "success" } }));
      }
      if (path === "/technician/chat/sessions/TCS-1/close") {
        return Promise.resolve(json({ ...session, status: "closed", messages: [] }));
      }
      if (path === "/smart-actions/communication-send/invoke" && init?.method === "POST") {
        return Promise.resolve(json({ status: "pending_approval", approval_id: 9 }));
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
    }));
  });

  it("loads sessions, starts a session, sends a bounded request, and closes it", async () => {
    render(<MemoryRouter><TechnicianChat /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Technician Chat" })).toBeInTheDocument();
    expect(await screen.findByText("communication delivery is not configured")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /TCS-1/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Client id (optional for a scoped technician token)"), { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: "New chat session" }));
    expect(await screen.findByText("Session TCS-2 started.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /TCS-1/ }));
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "summarize TCK-1001" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("I prepared a bounded ticket summary.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close session" }));
    expect(await screen.findByText("Session closed. Its operational history remains available for review.")).toBeInTheDocument();

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.some(([input, request]) => String(input) === "/technician/chat/sessions" && request?.method === "POST" && String(request.body).includes("acme"))).toBe(true);
    expect(calls.some(([input, request]) => String(input) === "/technician/chat/sessions/TCS-1/messages" && request?.method === "POST" && String(request.body).includes("summarize TCK-1001"))).toBe(true);
  });

  it("prepares a scoped Teams notification approval", async () => {
    render(<MemoryRouter><TechnicianChat /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Technician Chat" });
    fireEvent.change(screen.getByLabelText("Client id (optional for a scoped technician token)"), { target: { value: "acme" } });
    fireEvent.change(screen.getByLabelText("Notification channel"), { target: { value: "teams" } });
    fireEvent.change(screen.getByLabelText("Recipient or channel"), { target: { value: "support-ops" } });
    fireEvent.change(screen.getByLabelText("Notification message"), { target: { value: "TCK-1001 needs review" } });
    fireEvent.click(screen.getByRole("button", { name: "Prepare notification approval" }));

    expect(await screen.findByText("teams notification approval 9 created. Review it before delivery.")).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/smart-actions/communication-send/invoke",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"channel":"teams"')
      })
    ));
  });

  it("refreshes tenant-scoped notification activity after preparing an approval", async () => {
    render(<MemoryRouter><TechnicianChat /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Technician Chat" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh activity" }));

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === "/smart-actions/runs")).toBe(true));
    expect(screen.getByText("teams")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("does not expose chat controls to a viewer", async () => {
    dashboard.canWrite = false;
    render(<MemoryRouter><TechnicianChat /></MemoryRouter>);
    expect(await screen.findByText("Technician access required")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New chat session" })).not.toBeInTheDocument();
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });
});

function json(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
}
