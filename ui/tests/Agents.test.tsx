import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Agents } from "../src/screens/Agents";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true })
}));

describe("Agents", () => {
  const agent = {
    id: "agent-1",
    name: "MFA triage",
    description: "Bounded triage.",
    enabled: true,
    trigger: "manual",
    entity_type: "ticket",
    filters: {},
    enabled_tools: ["ticket-triage"],
    steps: [{ tool_id: "ticket-triage", payload: {} }],
    max_steps: 1,
    execution_timeout_seconds: 30,
    client_id: "acme",
    version: 1,
    run_once_per_entity: true,
    depends_on_agent_ids: [],
    execution_window_timezone: "UTC",
    context_sources: ["ticket"],
    approval_expiry_seconds: null
  };

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/agents" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([agent]), { status: 200 }));
      }
      if (path === "/tools" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([
          {
            id: "ticket-triage",
            name: "Ticket Triage",
            description: "Classify tickets.",
            risk_level: "low",
            required_role: "viewer",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "ticket-sla-assessment",
            name: "Assess ticket SLA risk",
            description: "Compare age with explicit thresholds.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "stale-ticket-sweep",
            name: "Sweep stale tickets",
            description: "Find old open tickets.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          }
        ]), { status: 200 }));
      }
      if (path === "/agents" && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ ...agent, context_sources: ["ticket", "knowledge"] }), { status: 200 }));
      }
      if (path === "/agents/agent-1/run" && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ run_id: 7 }), { status: 200 }));
      }
      if (path === "/agent-runs/7") {
        return Promise.resolve(new Response(JSON.stringify({
          id: 7,
          agent_id: "agent-1",
          entity_id: "TCK-1001",
          status: "completed",
          current_step: 1,
          revision_version: 1,
          state: { context: { ticket: {}, knowledge: {} } }
        }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("creates an agent with selected context and shows its run context", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Agents" })).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Assess ticket SLA risk" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Sweep stale tickets" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New triage" } });
    fireEvent.change(screen.getByLabelText("Approval deadline (hours, optional)"), { target: { value: "4" } });
    fireEvent.click(screen.getByLabelText("Local knowledge"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Ticket Triage" }));
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const ticket = screen.getByLabelText("Ticket for MFA triage");
    fireEvent.change(ticket, { target: { value: "TCK-1001" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(screen.getByText("Context loaded: ticket, knowledge")).toBeInTheDocument());
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST" && String(init.body).includes("knowledge")
    )).toBe(true);
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST" && String(init.body).includes("14400")
    )).toBe(true);
  });
});
