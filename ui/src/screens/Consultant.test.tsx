import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Consultant } from "./Consultant";

vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, clientId: "acme" }),
}));

describe("Consultant architecture decisions", () => {
  let rejectDiscoverySessions = false;
  let rejectBlueprints = false;
  let emptyBlueprints = false;
  let discoverySessionsStatus: number | null = null;
  let useCasesStatus: number | null = null;
  let rejectMonitoring = false;
  let rejectArchitecture = false;
  let rejectPlaybookGeneration = false;
  let holdPlaybookGeneration = false;
  let resolvePlaybookGeneration: (() => void) | null = null;

  beforeEach(() => {
    rejectDiscoverySessions = false;
    rejectBlueprints = false;
    emptyBlueprints = false;
    discoverySessionsStatus = null;
    useCasesStatus = null;
    rejectMonitoring = false;
    rejectArchitecture = false;
    rejectPlaybookGeneration = false;
    holdPlaybookGeneration = false;
    resolvePlaybookGeneration = null;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      const responses: Record<string, unknown> = {
        "/consultant/blueprints": emptyBlueprints ? [] : [{
          id: "bp-acme",
          client_id: "acme",
          created_by: "architect",
          created_at: "2026-08-17T00:00:00Z",
          updated_at: "2026-08-17T00:00:00Z",
          solution: { name: "Employee onboarding" },
          risk: "medium",
          agents: [],
          workflows: [],
        }],
        "/consultant/use-cases": { use_cases: [] },
        "/consultant/monitoring/agents": { agent_count: 0, total_runs: 0, failed_runs: 0 },
        "/consultant/discovery/sessions": [],
        "/consultant/blueprints/bp-acme/architecture": {
          blueprint_id: "bp-acme",
          client_id: "acme",
          solution: { name: "Employee onboarding" },
          risk: "medium",
          approval_policy: {},
          components: [],
          open_items: [],
          readiness: "ready",
          execution_started: false,
          deployment_started: false,
          decision_engine: {
            authority: "deterministic_local_catalogs_and_explicit_blueprint_evidence",
            decision_count: 1,
            unresolved_decision_count: 1,
            inference_started: false,
            execution_started: false,
            deployment_started: false,
          },
          decisions: [{
            id: "decision-1",
            capability: "Employee lookup",
            component_id: "onboarding",
            chosen_target: "microsoft_graph",
            status: "needs_review",
            why: "The directory is the system of record.",
            alternatives_considered: "Local cache",
            required_permissions: { unexpected: true },
            approval_requirements: ["Manager review"],
            open_questions: null,
          }],
        },
      };
      if (rejectBlueprints && path === "/consultant/blueprints") {
        return Promise.reject(new Error("Blueprints unavailable"));
      }
      if (rejectDiscoverySessions && path === "/consultant/discovery/sessions") {
        return Promise.reject(new Error("Forbidden"));
      }
      if (discoverySessionsStatus !== null && path === "/consultant/discovery/sessions") {
        return Promise.resolve(new Response(JSON.stringify({ detail: "section unavailable" }), { status: discoverySessionsStatus }));
      }
      if (useCasesStatus !== null && path === "/consultant/use-cases") {
        return Promise.resolve(new Response(JSON.stringify({ detail: "section unavailable" }), { status: useCasesStatus }));
      }
      if (rejectMonitoring && path === "/consultant/monitoring/agents") {
        return Promise.reject(new Error("Monitoring unavailable"));
      }
      if (rejectArchitecture && path === "/consultant/blueprints/bp-acme/architecture") {
        return Promise.reject(new Error("Architecture unavailable"));
      }
      if (path === "/consultant/blueprints/bp-acme/generate-playbook") {
        if (rejectPlaybookGeneration) {
          return Promise.resolve(new Response(JSON.stringify({ detail: "Playbook generation failed" }), { status: 500 }));
        }
        if (holdPlaybookGeneration) {
          return new Promise<Response>((resolve) => {
            resolvePlaybookGeneration = () => resolve(new Response(JSON.stringify({
              id: "entry-acme",
              source_playbook_id: "onboarding",
              definition: { id: "onboarding", name: "Onboarding", version: 1, trigger: "manual", description: "", risk_level: "medium", steps: [], output_evidence: [] },
              provenance: "blueprint:bp-acme",
              enabled: false,
              version: 1,
              created_at: "2026-08-18T00:00:00Z",
              updated_at: "2026-08-18T00:00:00Z",
              client_id: "acme",
            }), { status: 200 }));
          });
        }
        return Promise.resolve(new Response(JSON.stringify({ enabled: false }), { status: 200 }));
      }
      if (!(path in responses)) throw new Error(`Unexpected request: ${path}`);
      return Promise.resolve(new Response(JSON.stringify(responses[path]), { status: 200 }));
    }));
  });

  it("renders a tolerant decision summary and card, and omits empty sections", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Solutions Architect blueprints" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Architecture decisions" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));

    expect(await screen.findByRole("heading", { name: "Architecture decisions" })).toBeInTheDocument();
    expect(screen.getByText(/1 decisions · 1 need review · authority: Deterministic local catalogs and explicit blueprint evidence/)).toBeInTheDocument();
    expect(screen.getByText("Employee lookup")).toBeInTheDocument();
    expect(screen.getByText("Microsoft Graph")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("The directory is the system of record.")).toBeInTheDocument();
    expect(screen.getByText("Local cache")).toBeInTheDocument();
    expect(screen.getByText("Manager review")).toBeInTheDocument();
    expect(screen.getByText(/No inference started · No execution started · No deployment started/)).toBeInTheDocument();
  });

  it("isolates gated, empty, and retryable initial sections", async () => {
    discoverySessionsStatus = 403;
    useCasesStatus = 404;
    rejectMonitoring = true;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByText("Requires the Microsoft Admin pack or Microsoft Admin capability.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Extensions / Packs" })).toHaveAttribute("href", "/system/extensions");
    expect(screen.getByText("No Solutions Architect use cases are available.")).toBeInTheDocument();
    expect(await screen.findByText(/Unable to load agent monitoring/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry monitoring" })).toBeInTheDocument();
    expect(screen.queryByText("Some sections couldn't load")).not.toBeInTheDocument();

    rejectMonitoring = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry monitoring" }));
    expect(await screen.findByText("Agents in scope")).toBeInTheDocument();
  });

  it("gives an empty blueprint list a path into solution discovery", async () => {
    emptyBlueprints = true;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByText(/No solution blueprints yet\. Create one:/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Solution discovery below" })).toHaveAttribute("href", "#solution-discovery");
    expect(screen.getByRole("heading", { name: "Solution discovery" })).toBeInTheDocument();
  });

  it("keeps the blueprint list when discovery sessions fail", async () => {
    rejectDiscoverySessions = true;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Solutions Architect blueprints" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Employee onboarding/ })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("discovery sessions");
    expect(screen.queryByText("You do not have permission to do that")).not.toBeInTheDocument();
  });

  it("preserves the selected blueprint and architecture when blueprints refresh fails", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Architecture decisions" })).toBeInTheDocument();

    rejectBlueprints = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("blueprints");
    expect(screen.getByRole("button", { name: /Employee onboarding/ })).toHaveClass("selected");
    expect(screen.getByRole("heading", { name: "Architecture decisions" })).toBeInTheDocument();
  });

  it("does not clear an existing action message after a successful refresh", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    rejectArchitecture = true;
    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't connect to the appliance");

    rejectArchitecture = false;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input) === "/consultant/blueprints")).toHaveLength(2);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't connect to the appliance");
  });

  it("shows a successful playbook generation in its own status notice", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Architecture decisions" })).toBeInTheDocument();
    const generateButton = await screen.findByRole("button", { name: "Generate Playbook" });
    fireEvent.click(generateButton);

    const successNotice = await screen.findByRole("status");
    expect(successNotice).toHaveClass("notice", "success");
    expect(successNotice).toHaveTextContent("Draft playbook generated (disabled) — review and enable it in Playbooks.");
    expect(screen.getByRole("link", { name: "Playbooks" })).toHaveAttribute("href", "/playbooks");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enable|deploy/i })).not.toBeInTheDocument();
    const generationCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/blueprints/bp-acme/generate-playbook");
    expect(generationCall?.[1]).toMatchObject({ method: "POST" });
  });

  it("does not carry the Playbooks link into a later unrelated error", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Architecture decisions" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate Playbook" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Draft playbook generated (disabled)");

    rejectArchitecture = true;
    fireEvent.click(screen.getByRole("button", { name: /Employee onboarding/ }));

    const errorNotice = await screen.findByRole("alert");
    expect(errorNotice).toHaveTextContent("We couldn't connect to the appliance");
    expect(screen.queryByRole("link", { name: "Playbooks" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows the playbook generation error and disables the button while busy", async () => {
    holdPlaybookGeneration = true;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Architecture decisions" })).toBeInTheDocument();
    const generateButton = await screen.findByRole("button", { name: "Generate Playbook" });
    fireEvent.click(generateButton);
    expect(generateButton).toBeDisabled();

    resolvePlaybookGeneration?.();
    expect(await screen.findByRole("status")).toHaveTextContent("Draft playbook generated (disabled)");

    rejectPlaybookGeneration = true;
    fireEvent.click(screen.getByRole("button", { name: "Generate Playbook" }));
    const errorNotice = await screen.findByRole("alert");
    expect(errorNotice).toHaveClass("notice", "danger");
    expect(errorNotice).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Playbooks" })).not.toBeInTheDocument();
  });
});
