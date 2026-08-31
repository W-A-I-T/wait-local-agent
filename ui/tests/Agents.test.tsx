import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Agents } from "../src/screens/Agents";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({
    canWrite: true,
    connectors: [{ id: "timezest", name: "TimeZest", status: "not_configured", message: "not configured" }]
  })
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
    version: 2,
    run_once_per_entity: true,
    depends_on_agent_ids: [],
    execution_window_timezone: "UTC",
    context_sources: ["ticket"],
    approval_expiry_seconds: null,
    approval_required_tools: [],
    approval_rules: [],
    result_aware: false
  };

  beforeEach(() => {
    let currentAgent = agent;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/agents" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([currentAgent]), { status: 200 }));
      }
      if (path === "/tools" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([
          {
            id: "ticket-triage",
            name: "Ticket Triage",
            title: "Ticket classification",
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
          },
          {
            id: "timezest-scheduling-request-create",
            name: "TimeZest create scheduling request",
            description: "Create an approved scheduling request.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "nsight-run-task-now",
            name: "Run N-sight automated task now",
            description: "Run one mapped automated task after approval.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "nsight-check-config",
            name: "N-sight check configuration",
            description: "Read one mapped check configuration.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-antivirus-scans",
            name: "N-sight antivirus scan history",
            description: "Read mapped antivirus scans.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-antivirus-products",
            name: "N-sight supported antivirus products",
            description: "Read supported antivirus products.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-antivirus-definitions",
            name: "N-sight antivirus definition history",
            description: "Read antivirus definition history.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-antivirus-update-history",
            name: "N-sight antivirus update-check history",
            description: "Read antivirus update-check history.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-software-inventory",
            name: "N-sight software inventory",
            description: "Read mapped software inventory.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-hardware-inventory",
            name: "N-sight hardware inventory",
            description: "Read mapped hardware inventory.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-antivirus-scan-start",
            name: "Start N-sight antivirus scan",
            description: "Start a mapped antivirus scan after approval.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "nsight-antivirus-scan-cancel",
            name: "Cancel N-sight antivirus scan",
            description: "Cancel a mapped antivirus scan after approval.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "nsight-antivirus-scan-pause",
            name: "Pause N-sight antivirus scan",
            description: "Pause a mapped antivirus scan after approval.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "nsight-antivirus-scan-resume",
            name: "Resume N-sight antivirus scan",
            description: "Resume a mapped antivirus scan after approval.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "nsight-antivirus-quarantine",
            name: "N-sight antivirus quarantine lookup",
            description: "Read mapped antivirus quarantine records.",
            risk_level: "low",
            required_role: "technician",
            approval_required: false,
            access_mode: "read"
          },
          {
            id: "nsight-antivirus-quarantine-release",
            name: "Release N-sight antivirus quarantine",
            description: "Release selected quarantine items after approval.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "nsight-antivirus-quarantine-remove",
            name: "Remove N-sight antivirus quarantine",
            description: "Remove selected quarantine items after approval.",
            risk_level: "high",
            required_role: "technician",
            approval_required: true,
            access_mode: "write"
          },
          {
            id: "scalepad-compliance-health",
            name: "ScalePad compliance health",
            description: "Read one mapped compliance-health snapshot.",
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
      if (path === "/agents/agent-1" && init?.method === "PUT") {
        currentAgent = { ...currentAgent, version: 3, description: "Updated bounded triage." };
        return Promise.resolve(new Response(JSON.stringify(currentAgent), { status: 200 }));
      }
      if (path === "/agents/agent-1/revisions" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([
          { id: 2, agent_id: "agent-1", version: 2, definition: {}, created_at: "2026-08-09T12:00:00Z", client_id: "acme" },
          { id: 1, agent_id: "agent-1", version: 1, definition: {}, created_at: "2026-08-08T12:00:00Z", client_id: "acme" }
        ]), { status: 200 }));
      }
      if (path === "/agents/agent-1/revisions/1/diff/2" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify({ agent_id: "agent-1", from_version: 1, to_version: 2, changed: false, changes: [], client_id: "acme" }), { status: 200 }));
      }
      if (path === "/agents/agent-1/revisions/1/restore" && init?.method === "POST") {
        currentAgent = { ...currentAgent, version: 4, description: "Restored bounded triage." };
        return Promise.resolve(new Response(JSON.stringify(currentAgent), { status: 200 }));
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

  it("groups tools, shows live selection counts, and warns about missing connectors", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    expect(await screen.findByText("Core / ticket intelligence")).toBeInTheDocument();
    expect(screen.getByText("N-sight")).toBeInTheDocument();
    expect(screen.getByText("TimeZest")).toBeInTheDocument();
    expect(screen.getByText("3 tools · 0 selected")).toBeInTheDocument();
    expect(screen.getByText("connector not configured")).toBeInTheDocument();
    expect(screen.getAllByText("high").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("checkbox", { name: "Ticket Triage" }));
    expect(screen.getByText("1 of 8 tools selected")).toBeInTheDocument();
    expect(screen.getByText("3 tools · 1 selected")).toBeInTheDocument();
  });

  it("filters tools by name, title, and description and expands matching groups", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const search = await screen.findByRole("searchbox", { name: "Search tools" });
    fireEvent.change(search, { target: { value: "classification" } });
    expect(screen.getByRole("checkbox", { name: "Ticket Triage" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Assess ticket SLA risk" })).not.toBeInTheDocument();
    const coreDetails = screen.getByText("Core / ticket intelligence").closest("details");
    expect(coreDetails?.open).toBe(true);

    fireEvent.change(search, { target: { value: "quarantine" } });
    expect(screen.getByRole("checkbox", { name: "N-sight antivirus quarantine lookup" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Ticket Triage" })).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("checkbox", { name: "Ticket Triage · require approval" }));
    fireEvent.change(screen.getByLabelText("Ticket Triage priority conditions"), { target: { value: "high, urgent" } });
    fireEvent.change(screen.getByLabelText("Ticket Triage requester role conditions"), { target: { value: "technician, viewer" } });
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
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST" && String(init.body).includes("approval_required_tools")
    )).toBe(true);
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST" && String(init.body).includes("approval_rules") && String(init.body).includes("high")
    )).toBe(true);
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST" && String(init.body).includes("actor_role") && String(init.body).includes("technician")
    )).toBe(true);
  });

  it("edits an existing agent into a new revision", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Updated bounded triage." } });
    fireEvent.click(screen.getByRole("button", { name: "Save agent revision" }));

    await waitFor(() => expect(screen.getByText("Agent updated; a new revision is now available.")).toBeInTheDocument());
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input, init]) => String(input) === "/agents/agent-1" && init?.method === "PUT" && String(init.body).includes("Updated bounded triage.")
    )).toBe(true);
  });

  it("persists configured JSON inputs for selected tools", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    expect(await screen.findByRole("checkbox", { name: /TimeZest create scheduling request/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Scheduling agent" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /TimeZest create scheduling request/ }));
    fireEvent.change(screen.getByLabelText("TimeZest create scheduling request input JSON"), {
      target: {
        value: JSON.stringify({
          appointment_type_id: "apty_1",
          trigger_mode: "generate_url",
          resource_ids: ["agnt_1"],
          end_user_name: "Rodney Smith",
          end_user_email: "rodney@example.test"
        })
      }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(request).toBeDefined();
    expect(String(request?.[1]?.body)).toContain("apty_1");
    expect(String(request?.[1]?.body)).toContain("generate_url");
    expect(String(request?.[1]?.body)).toContain("rodney@example.test");
  });

  it("persists a bounded step failure policy", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    expect(await screen.findByRole("checkbox", { name: "Ticket Triage" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Resilient triage" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Ticket Triage" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Assess ticket SLA risk" }));
    fireEvent.change(screen.getByLabelText("Ticket Triage failure policy"), { target: { value: "fallback" } });
    fireEvent.change(screen.getByLabelText("Ticket Triage fallback tool"), { target: { value: "ticket-sla-assessment" } });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain('"mode":"fallback"');
    expect(String(request?.[1]?.body)).toContain('"fallback_tool_id":"ticket-sla-assessment"');
  });

  it("exposes the bounded N-sight automated-task input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const task = await screen.findByRole("checkbox", { name: /Run N-sight automated task now/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "N-sight maintenance" } });
    fireEvent.click(task);
    fireEvent.change(screen.getByLabelText("Run N-sight automated task now input JSON"), {
      target: { value: JSON.stringify({ device_id: "server:49324", check_id: "1304847" }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-run-task-now");
    expect(String(request?.[1]?.body)).toContain("1304847");
  });

  it("exposes the mapped N-sight check-configuration input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const config = await screen.findByRole("checkbox", { name: /N-sight check configuration/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Inspect check" } });
    fireEvent.click(config);
    fireEvent.change(screen.getByLabelText("N-sight check configuration input JSON"), {
      target: { value: JSON.stringify({ device_id: "server:49324", check_id: "1304847" }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-check-config");
    expect(String(request?.[1]?.body)).toContain("1304847");
  });

  it("exposes the mapped N-sight antivirus scan input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const scans = await screen.findByRole("checkbox", { name: /N-sight antivirus scan history/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Review antivirus scans" } });
    fireEvent.click(scans);
    fireEvent.change(screen.getByLabelText("N-sight antivirus scan history input JSON"), {
      target: { value: JSON.stringify({ device_id: "server:49324", include_details: true }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-antivirus-scans");
    expect(String(request?.[1]?.body)).toContain("include_details");
  });

  it("exposes the N-sight supported antivirus product input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const products = await screen.findByRole("checkbox", { name: /N-sight supported antivirus products/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Review antivirus products" } });
    fireEvent.click(products);
    fireEvent.change(screen.getByLabelText("N-sight supported antivirus products input JSON"), {
      target: { value: "{}" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-antivirus-products");
  });

  it("exposes the N-sight antivirus definition input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const definitions = await screen.findByRole("checkbox", { name: /N-sight antivirus definition history/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Review antivirus definitions" } });
    fireEvent.click(definitions);
    fireEvent.change(screen.getByLabelText("N-sight antivirus definition history input JSON"), {
      target: { value: JSON.stringify({ product_id: "bitdefender", max_results: 10 }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-antivirus-definitions");
    expect(String(request?.[1]?.body)).toContain("bitdefender");
  });

  it("exposes the mapped N-sight antivirus update-check history input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const history = await screen.findByRole("checkbox", { name: /N-sight antivirus update-check history/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Review antivirus update history" } });
    fireEvent.click(history);
    fireEvent.change(screen.getByLabelText("N-sight antivirus update-check history input JSON"), {
      target: { value: JSON.stringify({ device_id: "server:49324" }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-antivirus-update-history");
    expect(String(request?.[1]?.body)).toContain("server:49324");
  });

  it("exposes the mapped N-sight software inventory input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const software = await screen.findByRole("checkbox", { name: /N-sight software inventory/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Review software inventory" } });
    fireEvent.click(software);
    fireEvent.change(screen.getByLabelText("N-sight software inventory input JSON"), {
      target: { value: JSON.stringify({ device_id: "server:49324" }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-software-inventory");
    expect(String(request?.[1]?.body)).toContain("server:49324");
  });

  it("exposes the mapped N-sight hardware inventory input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const hardware = await screen.findByRole("checkbox", { name: /N-sight hardware inventory/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Review hardware inventory" } });
    fireEvent.click(hardware);
    fireEvent.change(screen.getByLabelText("N-sight hardware inventory input JSON"), {
      target: { value: JSON.stringify({ device_id: "server:49324" }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-hardware-inventory");
    expect(String(request?.[1]?.body)).toContain("server:49324");
  });

  it("exposes the approval-gated N-sight antivirus scan-start input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const start = await screen.findByRole("checkbox", { name: /Start N-sight antivirus scan/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Start antivirus scan" } });
    fireEvent.click(start);
    fireEvent.change(screen.getByLabelText("Start N-sight antivirus scan input JSON"), {
      target: { value: JSON.stringify({ device_id: "server:49324" }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("nsight-antivirus-scan-start");
    expect(String(request?.[1]?.body)).toContain("server:49324");
  });

  it("exposes the approval-gated N-sight antivirus scan pause and resume inputs", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    for (const [label, actionId, inputLabel] of [
      ["Pause N-sight antivirus scan", "nsight-antivirus-scan-pause", "Pause N-sight antivirus scan input JSON"],
      ["Resume N-sight antivirus scan", "nsight-antivirus-scan-resume", "Resume N-sight antivirus scan input JSON"]
    ]) {
      const control = await screen.findByRole("checkbox", { name: new RegExp(label) });
      fireEvent.change(screen.getByLabelText("Name"), { target: { value: label } });
      fireEvent.click(control);
      fireEvent.change(screen.getByLabelText(inputLabel), {
        target: { value: JSON.stringify({ device_id: "server:49324" }) }
      });
      fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

      await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
      const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
        ([input, init]) => String(input) === "/agents" && init?.method === "POST" && String(init.body).includes(actionId)
      );
      expect(String(request?.[1]?.body)).toContain(actionId);
    }
  });

  it("exposes the mapped ScalePad compliance-health input", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    const health = await screen.findByRole("checkbox", { name: /ScalePad compliance health/ });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Compliance review" } });
    fireEvent.click(health);
    fireEvent.change(screen.getByLabelText("ScalePad compliance health input JSON"), {
      target: { value: JSON.stringify({ client_id: "acme" }) }
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(screen.getByText("Agent created.")).toBeInTheDocument());
    const request = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.find(
      ([input, init]) => String(input) === "/agents" && init?.method === "POST"
    );
    expect(String(request?.[1]?.body)).toContain("scalepad-compliance-health");
    expect(String(request?.[1]?.body)).toContain("acme");
  });

  it("loads two selected revisions, renders their diff, and confirms restore with a refresh", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);

    expect(await screen.findByText("History and recovery")).toBeInTheDocument();
    fireEvent.click(screen.getByText("History and recovery"));
    expect(await screen.findByText("Revision history")).toBeInTheDocument();
    expect(screen.getAllByText(/Version 1/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Unsaved form state." } });
    fireEvent.change(screen.getByLabelText("From revision for MFA triage"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("To revision for MFA triage"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare revisions" }));
    expect(await screen.findByText("No changes.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getByRole("alertdialog", { name: "Confirm agent restore" })).toBeInTheDocument();
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input]) => String(input) === "/agents/agent-1/revisions/1/restore"
    )).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Confirm restore" }));
    await waitFor(() => expect(screen.getByText("Restored MFA triage version 1 as version 4.")).toBeInTheDocument());
    expect(screen.getByText("v4 · enabled")).toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toHaveValue("Restored bounded triage.");
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input]) => String(input) === "/agents"
    )).toBe(true);
  });
  it("shows loading while agent definitions are being fetched", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    render(<MemoryRouter><Agents /></MemoryRouter>);
    expect(screen.getByText("Loading agent definitions…")).toBeInTheDocument();
  });

  it("explains an empty agent catalog and points to the setup form", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))));
    render(<MemoryRouter><Agents /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "No agent definitions yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your first agent below" })).toHaveAttribute("href", "/#agent-form");
  });
});
