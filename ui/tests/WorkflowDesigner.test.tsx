import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowDesigner } from "../src/screens/WorkflowDesigner";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, isAdmin: true })
}));

describe("WorkflowDesigner", () => {
  const template = {
    id: "ticket-triage",
    name: "Ticket Triage",
    trigger: "ticket.created",
    description: "Classify tickets.",
    action_type: "ticket.triage",
    approval_required: true,
    risk_level: "medium",
    preview_fields: ["classification"],
    tool_id: "ticket.triage"
  };

  const definition = {
    format: "wait-local-agent.workflow-design",
    version: 1,
    nodes: [
      { id: "trigger", type: "trigger", label: "ticket.created", tool_id: null, config: {} },
      { id: "action", type: "action", label: "Ticket Triage", tool_id: "ticket.triage", config: {} },
      { id: "approval", type: "approval", label: "Human approval", tool_id: null, config: {} },
      { id: "end", type: "end", label: "Complete", tool_id: null, config: {} }
    ],
    edges: [
      { from: "trigger", to: "action" },
      { from: "action", to: "approval" },
      { from: "approval", to: "end" }
    ]
  };

  const entry = {
    id: "gallery-acme",
    source_template_id: "ticket-triage",
    name: "Ticket Triage",
    trigger: "ticket.created",
    description: "Classify tickets.",
    action_type: "ticket.triage",
    approval_required: true,
    risk_level: "medium",
    preview_fields: ["classification"],
    provenance: "designer",
    instructions: "",
    enabled: true,
    version: 1,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
    client_id: "acme",
    definition
  };

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/workflows/templates") {
        return Promise.resolve(new Response(JSON.stringify([template]), { status: 200 }));
      }
      if (path === "/workflow-templates/gallery" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path === "/workflow-templates/gallery" && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify(entry), { status: 200 }));
      }
      if (path === "/workflow-templates/gallery/gallery-acme" && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return Promise.resolve(new Response(JSON.stringify({ ...entry, definition: body.definition, version: 2 }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("creates, edits, connects, and saves a local graph", async () => {
    render(<MemoryRouter><WorkflowDesigner /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Workflow Designer" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create design" }));
    expect(await screen.findByRole("heading", { name: "Workflow canvas" })).toBeInTheDocument();
    expect(within(screen.getByLabelText("Workflow design canvas")).getByRole("button", { name: /Human approval/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /action Ticket Triage/i }));
    fireEvent.change(screen.getByLabelText("Node label"), { target: { value: "Review ticket" } });
    fireEvent.click(screen.getByRole("button", { name: "Save design" }));

    await waitFor(() => expect(screen.getByText(/Saved Ticket Triage as version 2/)).toBeInTheDocument());
    const calls = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls;
    const patchCall = calls.find(([input, init]) => String(input).endsWith("/gallery-acme") && init?.method === "PATCH");
    expect(patchCall).toBeDefined();
    expect(JSON.parse(String(patchCall?.[1]?.body)).definition.nodes[1].label).toBe("Review ticket");
  });

  it("shows loading and then explains when no local design exists", async () => {
    const releases: Array<(response: Response) => void> = [];
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { releases.push(resolve); })));
    render(<MemoryRouter><WorkflowDesigner /></MemoryRouter>);

    expect(screen.getByText("Loading workflow designs…")).toBeInTheDocument();
    releases.forEach((resolve) => resolve(new Response(JSON.stringify([]), { status: 200 })));

    expect(await screen.findByRole("heading", { name: "No design selected" })).toBeInTheDocument();
    expect(screen.getByText("Create a local design from a reviewed template to begin.")).toBeInTheDocument();
  });
});
