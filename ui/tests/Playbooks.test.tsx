import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Playbooks } from "../src/screens/Playbooks";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, clientId: "acme", selectedTicketId: "" })
}));

describe("Playbooks", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/msp/playbooks") {
        return Promise.resolve(new Response(JSON.stringify([{
          id: "ticket-intake-review",
          name: "Ticket Intake Review",
          version: 1,
          trigger: "ticket.created",
          description: "Review a new ticket.",
          risk_level: "low",
          steps: [{ id: "triage", name: "Triage", kind: "workflow", description: "Classify the ticket.", workflow_template_id: "ticket-triage", required_inputs: [] }],
          output_evidence: ["workflow_run_ids"]
        }]), { status: 200 }));
      }
      if (path === "/msp/playbook-entries") {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path === "/msp/playbook-subscriptions") {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path === "/msp/playbooks/ticket-intake-review/preview" && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ execution_started: false, approval_required: false, steps: [] }), { status: 200 }));
      }
      if (path === "/msp/playbooks/ticket-intake-review/runs" && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ status: "completed", execution_started: true }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("renders the library and wires preview and run to the MSP playbook routes", async () => {
    render(<MemoryRouter><Playbooks /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "MSP Playbooks" })).toBeInTheDocument();
    expect(screen.getByText("Ticket Intake Review")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/msp/playbooks/ticket-intake-review/preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ ticket_id: undefined, client_id: "acme", payload: {} })
      })
    ));

    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/msp/playbooks/ticket-intake-review/runs",
      expect.objectContaining({ method: "POST" })
    ));
    expect(await screen.findByText("Started Ticket Intake Review.")).toBeInTheDocument();
  });
});
