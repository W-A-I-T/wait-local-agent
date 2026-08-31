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

  it("renders required playbook inputs and keeps form and raw JSON in sync", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/msp/playbooks") {
        return Promise.resolve(new Response(JSON.stringify([{
          id: "software-inventory-review",
          name: "Software Inventory Review",
          version: 1,
          trigger: "schedule.daily",
          description: "Review software.",
          risk_level: "low",
          steps: [{ id: "inventory", name: "Inventory", kind: "workflow", description: "Read software.", required_inputs: ["device_id"] }],
          output_evidence: ["workflow_run_ids"]
        }]), { status: 200 }));
      }
      if (path === "/msp/playbook-entries") {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path === "/msp/playbook-subscriptions") {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path === "/msp/playbooks/software-inventory-review/preview" && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({ execution_started: false, approval_required: false, steps: [] }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Playbooks /></MemoryRouter>);

    const deviceId = await screen.findByLabelText("Device id");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Device id is required.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/preview"))).toBe(false);

    fireEvent.change(deviceId, { target: { value: "device-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Raw JSON (advanced)" }));
    const raw = screen.getByLabelText("Raw JSON");
    expect((raw as HTMLTextAreaElement).value).toContain('"device_id": "device-1"');
    fireEvent.change(raw, { target: { value: '{"device_id":"device-2"}' } });
    fireEvent.click(screen.getByRole("button", { name: "Back to form" }));
    expect(screen.getByLabelText("Device id")).toHaveValue("device-2");

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/msp/playbooks/software-inventory-review/preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ ticket_id: undefined, client_id: "acme", payload: { device_id: "device-2" } })
      })
    ));
  });

  it("edits a published entry with only the backend-supported patch fields", async () => {
    const entry = {
      id: "entry-qbr",
      source_playbook_id: "ticket-intake-review",
      definition: {
        id: "ticket-intake-review",
        name: "Acme QBR",
        version: 1,
        trigger: "ticket.created",
        description: "Review Acme tickets.",
        risk_level: "low",
        steps: [{ id: "triage", name: "Triage", kind: "workflow", description: "Classify the ticket.", workflow_template_id: "ticket-triage", required_inputs: [] }],
        output_evidence: ["workflow_run_ids"],
        local_fixture: true
      },
      provenance: "Published from review.",
      enabled: true,
      version: 1,
      created_at: "2026-08-08T00:00:00Z",
      updated_at: "2026-08-08T00:00:00Z",
      client_id: "acme"
    };
    let currentEntry = entry;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/msp/playbooks") {
        return Promise.resolve(new Response(JSON.stringify([{
          id: "ticket-intake-review",
          name: "Ticket Intake Review",
          version: 1,
          trigger: "ticket.created",
          description: "Review a new ticket.",
          risk_level: "low",
          steps: entry.definition.steps,
          output_evidence: ["workflow_run_ids"]
        }]), { status: 200 }));
      }
      if (path === "/msp/playbook-entries" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([currentEntry]), { status: 200 }));
      }
      if (path === "/msp/playbook-subscriptions") {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path === "/msp/playbook-entries/entry-qbr" && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        currentEntry = {
          ...currentEntry,
          definition: { ...currentEntry.definition, ...body.definition, version: 2 },
          provenance: body.provenance,
          enabled: body.enabled,
          version: 2
        };
        return Promise.resolve(new Response(JSON.stringify(currentEntry), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Playbooks /></MemoryRouter>);

    expect(await screen.findByText("Acme QBR")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Acme QBR updated" } });
    fireEvent.change(screen.getByLabelText("Provenance"), { target: { value: "Updated by Acme operator." } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Saved Acme QBR updated as version 2.")).toBeInTheDocument();
    const patchCall = fetchMock.mock.calls.find(([input, init]) => String(input) === "/msp/playbook-entries/entry-qbr" && init?.method === "PATCH");
    expect(patchCall).toBeDefined();
    const body = JSON.parse(String(patchCall?.[1]?.body));
    expect(Object.keys(body).sort()).toEqual(["definition", "enabled", "provenance"]);
    expect(Object.keys(body.definition).sort()).toEqual(["description", "local_fixture", "name", "output_evidence", "risk_level", "steps", "trigger"]);
    expect(body.definition.name).toBe("Acme QBR updated");
    expect(body.provenance).toBe("Updated by Acme operator.");
  });

  it("loads two selected revisions, renders their diff, and confirms restore", async () => {
    const entry = {
      id: "entry-qbr",
      source_playbook_id: "ticket-intake-review",
      definition: {
        id: "ticket-intake-review",
        name: "Acme QBR",
        version: 3,
        trigger: "ticket.created",
        description: "Review Acme tickets.",
        risk_level: "low",
        steps: [{ id: "triage", name: "Triage", kind: "workflow", description: "Classify the ticket.", workflow_template_id: "ticket-triage", required_inputs: [] }],
        output_evidence: ["workflow_run_ids"],
        local_fixture: true
      },
      provenance: "Current review.",
      enabled: true,
      version: 3,
      created_at: "2026-08-08T00:00:00Z",
      updated_at: "2026-08-08T03:00:00Z",
      client_id: "acme"
    };
    let currentEntry = entry;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/msp/playbooks") {
        return Promise.resolve(new Response(JSON.stringify([{
          id: "ticket-intake-review",
          name: "Ticket Intake Review",
          version: 1,
          trigger: "ticket.created",
          description: "Review a new ticket.",
          risk_level: "low",
          steps: entry.definition.steps,
          output_evidence: ["workflow_run_ids"]
        }]), { status: 200 }));
      }
      if (path === "/msp/playbook-entries" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([currentEntry]), { status: 200 }));
      }
      if (path === "/msp/playbook-subscriptions") {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path === "/msp/playbook-entries/entry-qbr/revisions") {
        return Promise.resolve(new Response(JSON.stringify([
          { id: 3, playbook_id: "entry-qbr", version: 3, snapshot: { provenance: "Current review." }, created_at: "2026-08-08T03:00:00Z", client_id: "acme" },
          { id: 2, playbook_id: "entry-qbr", version: 2, snapshot: { provenance: "Second review." }, created_at: "2026-08-08T02:00:00Z", client_id: "acme" },
          { id: 1, playbook_id: "entry-qbr", version: 1, snapshot: { provenance: "First review." }, created_at: "2026-08-08T01:00:00Z", client_id: "acme" }
        ]), { status: 200 }));
      }
      if (path === "/msp/playbook-entries/entry-qbr/revisions/diff?from_version=1&to_version=2") {
        return Promise.resolve(new Response(JSON.stringify({
          playbook_id: "entry-qbr",
          from_version: 1,
          to_version: 2,
          changed_fields: ["provenance"],
          from: { provenance: "First review." },
          to: { provenance: "Second review." }
        }), { status: 200 }));
      }
      if (path === "/msp/playbook-entries/entry-qbr/revisions/2/restore" && init?.method === "POST") {
        currentEntry = { ...currentEntry, version: 4, updated_at: "2026-08-08T04:00:00Z" };
        return Promise.resolve(new Response(JSON.stringify(currentEntry), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Playbooks /></MemoryRouter>);

    expect(await screen.findByText("Acme QBR")).toBeInTheDocument();
    fireEvent.click(screen.getByText("History and recovery"));
    expect(await screen.findByText("Version 3")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("From revision for Acme QBR"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("To revision for Acme QBR"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare revisions" }));

    expect(await screen.findByText("Changes: v1 → v2")).toBeInTheDocument();
    expect(screen.getByText("First review.")).toBeInTheDocument();
    expect(screen.getByText("Second review.")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Restore" })[1]);
    expect(screen.getByRole("alertdialog", { name: "Confirm playbook restore" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/restore"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Confirm restore" }));
    expect(await screen.findByText("Restored Acme QBR as version 4.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => String(input) === "/msp/playbook-entries/entry-qbr/revisions/2/restore" && init?.method === "POST")).toBe(true);
  });
});
