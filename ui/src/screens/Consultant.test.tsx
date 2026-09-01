import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Consultant } from "./Consultant";

const dashboard = vi.hoisted(() => ({
  canWrite: true,
  clientId: "acme",
  authState: "authenticated",
  writeHealth: { status: "blocked" },
}));

vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => dashboard,
}));

describe("Consultant architecture decisions", () => {
  let rejectDiscoverySessions = false;
  let rejectBlueprints = false;
  let emptyBlueprints = false;
  let discoverySessionsStatus: number | null = null;
  let discoverySessionsDetail: unknown = "section unavailable";
  let useCasesStatus: number | null = null;
  let rejectMonitoring = false;
  let rejectArchitecture = false;
  let environmentStatus: number | null = null;
  let governanceStatus: number | null = null;
  let governanceDetail: unknown = "governance unavailable";
  let evaluationStatus: number | null = null;
  let deliveryStatus: number | null = null;
  let rejectPlaybookGeneration = false;
  let holdPlaybookGeneration = false;
  let resolvePlaybookGeneration: (() => void) | null = null;

  beforeEach(() => {
    rejectDiscoverySessions = false;
    rejectBlueprints = false;
    emptyBlueprints = false;
    discoverySessionsStatus = null;
    discoverySessionsDetail = "section unavailable";
    useCasesStatus = null;
    rejectMonitoring = false;
    rejectArchitecture = false;
    environmentStatus = null;
    governanceStatus = null;
    governanceDetail = "governance unavailable";
    evaluationStatus = null;
    deliveryStatus = null;
    dashboard.authState = "authenticated";
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
        "/consultant/blueprints/bp-acme": {
          id: "bp-acme",
          client_id: "acme",
          created_by: "architect",
          created_at: "2026-08-17T00:00:00Z",
          updated_at: "2026-08-17T00:00:00Z",
          solution: { name: "Employee onboarding" },
          risk: "medium",
          agents: [],
          workflows: [],
        },
      };
      if (rejectBlueprints && path === "/consultant/blueprints") {
        return Promise.reject(new Error("Blueprints unavailable"));
      }
      if (rejectDiscoverySessions && path === "/consultant/discovery/sessions") {
        return Promise.reject(new Error("Forbidden"));
      }
      if (discoverySessionsStatus !== null && path === "/consultant/discovery/sessions") {
        return Promise.resolve(new Response(JSON.stringify({ detail: discoverySessionsDetail }), { status: discoverySessionsStatus }));
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
      if (environmentStatus !== null && path === "/consultant/environment-discovery") {
        return Promise.resolve(new Response(JSON.stringify({ detail: "environment unavailable" }), { status: environmentStatus }));
      }
      if (governanceStatus !== null && path === "/consultant/governance/evaluate") {
        return Promise.resolve(new Response(JSON.stringify({ detail: governanceDetail }), { status: governanceStatus }));
      }
      if (evaluationStatus !== null && path === "/consultant/evaluations") {
        return Promise.resolve(new Response(JSON.stringify({ detail: "controlled evaluation execution requires local demo mode with writes disabled" }), { status: evaluationStatus }));
      }
      if (deliveryStatus !== null && path === "/consultant/delivery-plan") {
        return Promise.resolve(new Response(JSON.stringify({ detail: "delivery unavailable" }), { status: deliveryStatus }));
      }
      if (path === "/consultant/environment-discovery") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.environment-discovery",
          format_version: 1,
          client_id: "acme",
          source: "customer_declarations_and_local_connector_configuration",
          probe_requested: true,
          probe_performed: true,
          systems: Array.from({ length: 13 }, (_, index) => ({
            id: "system-" + (index + 1),
            name: index === 0 ? "HaloPSA" : "System " + (index + 1),
            kind: "connector",
            connector_id: index === 0 ? "halopsa" : "connector-" + (index + 1),
            status: index === 0 ? "authorized" : "not_configured",
            provider_status: index === 0 ? "configured" : "not_configured",
            evidence: ["local_connector_configuration"],
            tenant_scope: "acme",
            probe: index === 0 ? { status: "passed", layer: "connector", message: "healthy" } : { status: "not_run", layer: "not_run", message: "not requested" },
          })),
          unresolved: [],
          limitations: [],
          readiness: "needs_environment_verification",
          inference_started: false,
          execution_started: false,
          deployment_started: false,
        }), { status: 200 }));
      }
      if (path === "/consultant/governance/evaluate") {
        return Promise.resolve(new Response(JSON.stringify({
          client_id: "acme",
          status: "needs_review",
          finding_counts: { high: 0, medium: 1, info: 0 },
          findings: [{ severity: "medium", code: "architecture_review_required", message: "Review required." }],
          connectors: [],
          policy_mapping: [{ policy_id: "approval_for_state_changes", status: "needs_review", evidence: "Review" }],
          authorization_changed: false,
          execution_started: false,
          deployment_started: false,
        }), { status: 200 }));
      }
      if (path === "/consultant/evaluations") {
        return Promise.resolve(new Response(JSON.stringify({
          case_count: 1,
          dimensions: { functional: 100, tenant_isolation: 100 },
          production_readiness: "pass",
          execution_started: dashboard.authState === "demo",
          execution_mode: dashboard.authState === "demo" ? "controlled" : "observation",
          cases: [{ id: "architecture-review", checks: { functional: true }, passed: true }],
        }), { status: 200 }));
      }
      if (path === "/consultant/delivery-plan") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.consultant-delivery-plan",
          format_version: 1,
          client_id: "acme",
          summary: {},
          checks: { architecture: false, evaluation: true, governance: false, credentials: true },
          production_readiness: "needs_review",
          deployment_targets: ["Teams", "Power Automate"],
          review_package: null,
          review_package_generated: false,
          review_package_digest: null,
          delivery_bundle: null,
          delivery_bundle_generated: false,
          delivery_bundle_digest: null,
          delivery_bundle_status: "not_generated",
          deployable_source_package: null,
          deployable_source_package_generated: false,
          deployable_source_package_digest: null,
          deployment_package_generated: false,
          deployment_package_status: "not_generated",
          production_deployment_requires_approval: true,
          execution_started: false,
          deployment_started: false,
          authorization_changed: false,
        }), { status: 200 }));
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

  it("loads blueprint detail, probes the environment matrix, and passes review results through the chain", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Blueprint detail" })).toBeInTheDocument();
    expect(screen.getByText("Created by")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Probe environment" }));
    const matrix = await screen.findByRole("table", { name: "Environment status matrix" });
    expect(matrix.querySelectorAll("tbody tr")).toHaveLength(13);
    expect(screen.getByText("authorized", { exact: false })).toBeInTheDocument();
    const environmentCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/environment-discovery");
    expect(environmentCall?.[1]).toMatchObject({
      body: expect.stringContaining('"probe":true'),
    });

    fireEvent.click(screen.getByRole("button", { name: "Evaluate governance" }));
    expect(await screen.findByRole("heading", { name: "Governance checklist" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run agent evaluation" }));
    expect(await screen.findByRole("heading", { name: "Evaluation checklist" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Build delivery plan" }));
    expect(await screen.findByText(/not_generated handoff/)).toBeInTheDocument();

    const deliveryCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/delivery-plan");
    const deliveryBody = JSON.parse(String(deliveryCall?.[1]?.body));
    expect(deliveryBody.architecture).toMatchObject({ blueprint_id: "bp-acme" });
    expect(deliveryBody.governance).toMatchObject({ status: "needs_review" });
    expect(deliveryBody.evaluation).toMatchObject({ production_readiness: "pass" });
    expect(deliveryBody.review_artifacts[0]).toMatchObject({ client_id: "acme", probe_requested: true });
  });

  it("labels controlled evaluation accurately and sends execution only in demo Safe Mode", async () => {
    dashboard.authState = "demo";
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Evaluate & ship" })).toBeInTheDocument();
    const mode = screen.getByLabelText("Evaluation mode");
    expect(screen.getByRole("option", { name: "Controlled local execution (demo + Safe Mode only)" })).not.toBeDisabled();
    fireEvent.change(mode, { target: { value: "controlled" } });
    fireEvent.change(screen.getByLabelText("Evaluation agent ID"), { target: { value: "agent-acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Run agent evaluation" }));

    expect(await screen.findByText(/controlled local execution recorded/)).toBeInTheDocument();
    const evaluationCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/evaluations");
    const evaluationBody = JSON.parse(String(evaluationCall?.[1]?.body));
    expect(evaluationBody.execution).toMatchObject({ agent_id: "agent-acme", client_id: "acme" });
  });

  it("keeps new section failures retryable or gated", async () => {
    environmentStatus = 500;
    governanceStatus = 403;
    governanceDetail = "authenticated principal has no tenant";
    evaluationStatus = 409;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    fireEvent.click(screen.getByRole("button", { name: "Probe environment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("environment evidence");
    expect(screen.getByRole("button", { name: "Retry environment probe" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Evaluate governance" }));
    expect(await screen.findByText(/This action needs a specific client selected/)).toBeInTheDocument();
    expect(screen.queryByText(/Requires the Microsoft Admin pack/)).not.toBeInTheDocument();

    dashboard.authState = "demo";
    environmentStatus = null;
    governanceStatus = null;
    governanceDetail = "governance unavailable";
    fireEvent.click(screen.getByRole("button", { name: "Retry environment probe" }));
    fireEvent.click(screen.getByRole("button", { name: "Evaluate governance" }));
    expect(await screen.findByRole("heading", { name: "Governance checklist" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run agent evaluation" }));
    expect(await screen.findByRole("button", { name: "Retry evaluation" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("controlled evaluation execution requires local demo mode with writes disabled");
  });

  it("isolates gated, empty, and retryable initial sections", async () => {
    discoverySessionsStatus = 403;
    discoverySessionsDetail = {
      code: "capability_required",
      capability: "microsoft_admin",
      reason: "no_grant",
      remediation: "grant_capability",
    };
    useCasesStatus = 404;
    rejectMonitoring = true;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByText("Requires the Microsoft Admin pack or Microsoft Admin capability.")).toBeInTheDocument();
    expect(screen.getByText(/grant_capability/)).toBeInTheDocument();
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
