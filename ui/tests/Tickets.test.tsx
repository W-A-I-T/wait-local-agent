import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Tickets } from "../src/screens/Tickets";

vi.mock("../src/app/DashboardContext", () => ({
  defaultFieldText: "note=Reviewed by WAIT Local Agent",
  useDashboard: () => ({
    haloTickets: [],
    selectedTicketId: "",
    selectTicket: vi.fn(),
    actionTypes: ["add_note"],
    canWrite: true,
    busyId: null,
    createDraft: vi.fn()
  })
}));

describe("Tickets customer conversation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/tickets/EUS-1/end-user-messages" && !init?.method) {
        return Promise.resolve(json([
          { id: 1, ticket_id: "EUS-1", role: "requester", body: "I cannot sign in", created_at: "2026-08-10T00:00:00Z" }
        ]));
      }
      if (path === "/tickets/EUS-1/end-user-messages" && init?.method === "POST") {
        return Promise.resolve(json({ id: 2, ticket_id: "EUS-1", role: "support", body: "We are reviewing this.", created_at: "2026-08-10T00:01:00Z" }));
      }
      if (path === "/tickets/EUS-1/end-user-messages/1/halopsa-drafts" && init?.method === "POST") {
        return Promise.resolve(json({ approval_request_id: 7 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("loads and adds a tenant-scoped support reply", async () => {
    render(<Tickets />);
    expect(screen.getByText("approval drafts enabled")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("EUS-..."), { target: { value: "EUS-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Load conversation" }));
    expect(await screen.findByText("I cannot sign in")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Write a response for the local end-user portal"), { target: { value: "We are reviewing this." } });
    fireEvent.click(screen.getByRole("button", { name: "Add support reply" }));
    expect(await screen.findByText("Reply added to the local customer conversation.")).toBeInTheDocument();
    expect(screen.getByText("We are reviewing this.")).toBeInTheDocument();

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/tickets/EUS-1/end-user-messages",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "We are reviewing this." }) })
    ));
  });

  it("creates an approval draft for a verified HaloPSA ticket", async () => {
    render(<Tickets />);

    fireEvent.change(screen.getByPlaceholderText("EUS-..."), { target: { value: "EUS-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Load conversation" }));
    await screen.findByText("I cannot sign in");

    fireEvent.change(screen.getByLabelText("HaloPSA ticket ID"), { target: { value: "HALO-42" } });
    fireEvent.change(screen.getByLabelText("Message to sync"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Prepare HaloPSA approval" }));

    expect(await screen.findByText("HaloPSA approval draft 7 created. Review it before execution.")).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/tickets/EUS-1/end-user-messages/1/halopsa-drafts",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ external_ticket_id: "HALO-42" }) })
    ));
  });
});

function json(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
