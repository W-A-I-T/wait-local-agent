import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Consultant } from "./Consultant";

const dashboard = vi.hoisted(() => ({
  canWrite: true,
  clientId: "acme",
  selectedClientId: "acme",
  clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
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
  let connectorStatus: number | null = null;
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
    connectorStatus = null;
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
        "/consultant/use-cases": {
          use_cases: [{
            id: "use-case-1",
            title: "Employee identity sync",
            category: "identity",
            business_goal: "Keep employee records aligned.",
            services: ["Microsoft Graph"],
            agent_roles: ["identity-reader"],
            outputs: ["employee record"],
            approval_boundaries: ["No writes"],
          }],
        },
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
          supervisor: {
            mode: "delegated",
            children: [
              { id: "identity-reader", kind: "reader", context_policy: "bounded" },
              { id: "approval-checker", kind: "reviewer", context_policy: "bounded" },
            ],
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
      if (path === "/consultant/supervisor/plan") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.supervisor-delegation-plan",
          format_version: 1,
          client_id: "acme",
          supervisor: {
            id: "consultant-supervisor",
            mode: "supervisor",
            max_depth: 1,
            recursion: "disabled",
            task: "Employee onboarding",
            children: [
              { id: "identity-reader", name: "Identity review", enabled: true, tool_ids: ["ticket-triage"], depends_on_agent_ids: [], context_policy: "tenant_scoped_task_and_structured_prior_results", result_contract: {} },
              { id: "approval-checker", name: "Approval review", enabled: true, tool_ids: ["ticket-triage"], depends_on_agent_ids: ["identity-reader"], context_policy: "tenant_scoped_task_and_structured_prior_results", result_contract: {} },
            ],
            selection: "explicit_child_agent_ids",
          },
          assignments: [
            { sequence: 1, child_agent_id: "identity-reader", input_contract: {} },
            { sequence: 2, child_agent_id: "approval-checker", input_contract: {} },
          ],
          context_policy: "pass only bounded structured results within the blueprint tenant",
          retry_policy: { max_retries_per_child: 0, retryable_statuses: ["failed"], attempts_are_lineage_bound: true },
          cancellation_policy: { supported: true, target: "queued_or_approval_paused_child_run_id", stops_before_next_child: true },
          delegation_started: false,
          execution_started: false,
          approval_requests_created: false,
          cross_tenant_context: false,
        }), { status: 200 }));
      }
      if (path === "/consultant/supervisor/run") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.supervisor-execution",
          format_version: 1,
          client_id: "acme",
          entity_id: "TCK-1001",
          status: "completed",
          supervisor: {
            id: "consultant-supervisor",
            mode: "supervisor",
            max_depth: 1,
            recursion: "disabled",
            task: "Employee onboarding",
            ordered_child_agent_ids: ["identity-reader", "approval-checker"],
            lineage_contract: "supervisor_id, child_agent_id, sequence, attempt, and retry_of_run_id",
          },
          children: [
            { agent_id: "identity-reader", run_id: 41, sequence: 1, status: "completed", attempt: 1, retry_count: 0 },
            { agent_id: "approval-checker", run_id: 42, sequence: 2, status: "completed", attempt: 1, retry_count: 0 },
          ],
          resumption: { completed_run_ids: [41, 42], pending_run_id: null, next_child_agent_id: null },
          delegation_started: true,
          execution_started: true,
          approval_requests_created: false,
          retry_policy: { max_retries_per_child: 0, retryable_statuses: ["failed"] },
          cancellation: { requested_run_id: null, applied: false },
          cross_tenant_context: false,
        }), { status: 200 }));
      }
      if (path === "/consultant/copilot-studio/plan") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.copilot-studio-plan",
          format_version: 1,
          client_id: "acme",
          target: "microsoft_copilot_studio",
          copilot: { name: "Support assistant", business_goal: "Help operators answer customer questions." },
          topics: [{ id: "ticket-status", name: "Ticket status", trigger_phrases: ["check my ticket"] }],
          knowledge_sources: ["Support handbook"],
          actions: [{ id: "lookup_ticket", connector_id: "customer-api", method: "POST", approval_required: true }],
          requires_approval: true,
          credentials_included: false,
          generation_status: "review_only",
          provider_verification: "not_run",
          execution_started: false,
          deployment_started: false,
          open_items: ["Operator verification remains required."],
        }), { status: 200 }));
      }
      if (path === "/consultant/connectors/openapi/validate") {
        if (connectorStatus !== null) {
          return Promise.resolve(new Response(JSON.stringify({ detail: "definition must use OpenAPI 2.0 (swagger=2.0)" }), { status: connectorStatus }));
        }
        return Promise.resolve(new Response(JSON.stringify({
          valid: true,
          connector: {
            format: "wait-local-agent.power-platform.custom-connector",
            format_version: 1,
            connector_id: "customer-api",
            display_name: "Customer API",
            api_version: "1.0",
            host: "api.example.com",
            base_path: "/",
            authentication: [{ name: "oauth", type: "oauth2", in: null, authorization_url_present: true }],
            actions: [{ id: "list_customers", method: "GET", path: "/customers", summary: "List customers", parameters: [], response_statuses: ["200"] }],
            credentials_included: false,
            deployment_started: false,
          },
        }), { status: 200 }));
      }
      if (path === "/consultant/connectors/openapi/generate") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.power-platform.custom-connector",
          format_version: 1,
          connector_id: "customer-api",
          display_name: "Customer API",
          api_version: "1.0",
          host: "api.example.com",
          base_path: "/",
          authentication: [{ name: "oauth", type: "oauth2", in: null, authorization_url_present: true }],
          actions: [{ id: "list_customers", method: "GET", path: "/customers", summary: "List customers", parameters: [], response_statuses: ["200"] }],
          credentials_included: false,
          deployment_started: false,
        }), { status: 200 }));
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
    expect(screen.getAllByRole("heading", { name: "Blueprint walkthrough" })).toHaveLength(2);
    expect(screen.getByText(/Run the selected blueprint through discovery, architecture/)).toBeInTheDocument();
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
    expect(screen.getByText(/No inference started · No live run recorded · No deployment started/)).toBeInTheDocument();
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
    expect(await screen.findByText(/The delivery review is/)).toBeInTheDocument();

    const deliveryCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/delivery-plan");
    const deliveryBody = JSON.parse(String(deliveryCall?.[1]?.body));
    expect(deliveryBody.architecture).toMatchObject({ blueprint_id: "bp-acme" });
    expect(deliveryBody.governance).toMatchObject({ status: "needs_review" });
    expect(deliveryBody.evaluation).toMatchObject({ production_readiness: "pass" });
    expect(deliveryBody.review_artifacts[0]).toMatchObject({ client_id: "acme", probe_requested: true });
  }, 15000);

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

  it("does not present a dead delivery warning or synthetic item statuses", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    const useCaseCard = (await screen.findByText("Employee identity sync")).closest("article");
    expect(useCaseCard).not.toBeNull();
    expect(useCaseCard?.querySelector(".status-chip")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Architecture decisions" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Solution delivery" })).toHaveAttribute("href", "/consultant/solution-delivery");
    expect(screen.queryByText(/not available in this checkout/)).not.toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Supervisor delegation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plan delegation" })).toBeInTheDocument();
    expect(screen.queryByText("Needs attention")).not.toBeInTheDocument();
  });

  it("plans and runs supervisor delegation with a ticket-bound approval gate", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    expect(await screen.findByRole("heading", { name: "Supervisor delegation" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Plan delegation" }));
    expect(await screen.findByText("1. Identity review")).toBeInTheDocument();
    expect(screen.getByText("2. Approval review")).toBeInTheDocument();

    const planCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/supervisor/plan");
    expect(JSON.parse(String(planCall?.[1]?.body))).toEqual({
      client_id: "acme",
      task: "Employee onboarding",
      child_agent_ids: ["identity-reader", "approval-checker"],
      max_retries: 0,
    });

    fireEvent.click(screen.getByRole("button", { name: "Run delegation" }));
    expect(await screen.findByText("Delegation completed")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Follow up in Activity" })).toHaveLength(2);
    const runCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/supervisor/run");
    expect(JSON.parse(String(runCall?.[1]?.body))).toMatchObject({
      client_id: "acme",
      entity_id: "TCK-1001",
      task: "Employee onboarding",
      child_agent_ids: ["identity-reader", "approval-checker"],
      max_retries: 0,
    });
  });

  it("requires an existing entity before supervisor execution", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Plan delegation" }));
    expect(await screen.findByText("1. Identity review")).toBeInTheDocument();
    const supervisorHeading = screen.getByRole("heading", { name: "Supervisor delegation" });
    const supervisorPanel = supervisorHeading.closest(".panel-subsection");
    expect(supervisorPanel).not.toBeNull();
    if (!supervisorPanel) throw new Error("Missing supervisor delegation panel");
    const supervisorView = within(supervisorPanel as HTMLElement);
    fireEvent.change(supervisorView.getByLabelText("Existing ticket or entity ID"), { target: { value: "" } });
    fireEvent.click(supervisorView.getByRole("button", { name: "Run delegation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("existing ticket ID");
    expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input) === "/consultant/supervisor/run")).toHaveLength(0);
  });

  it("builds the Copilot Studio request shape and renders review-only boundaries", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Add source" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Knowledge source 1" }), { target: { value: "Support handbook" } });
    fireEvent.click(screen.getByRole("button", { name: "Add action" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Action 1 ID" }), { target: { value: "lookup_ticket" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Action 1 connector ID" }), { target: { value: "customer-api" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Action 1 method" }), { target: { value: "POST" } });
    fireEvent.click(screen.getByRole("button", { name: "Build Copilot Studio plan" }));

    expect(await screen.findByText("generation_status: review_only")).toBeInTheDocument();
    expect(screen.getByText("execution_started: false")).toBeInTheDocument();
    expect(screen.getByText("deployment_started: false")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Open items" })).toBeInTheDocument();
    const call = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/copilot-studio/plan");
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toEqual({
      client_id: "acme",
      copilot_name: "Support assistant",
      business_goal: "Help operators answer bounded customer support questions.",
      topics: [{ id: "ticket-status", name: "Ticket status", trigger_phrases: ["check my ticket"] }],
      knowledge_sources: ["Support handbook"],
      actions: [{ id: "lookup_ticket", connector_id: "customer-api", method: "POST", approval_required: true }],
    });
  });

  it("enforces the Copilot topic limit in the editor", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    const addTopic = await screen.findByRole("button", { name: "Add topic" });
    act(() => {
      for (let index = 0; index < 31; index += 1) fireEvent.click(addTopic);
    });
    expect(addTopic).toBeDisabled();
  });

  it("enforces the Copilot trigger phrase limit in the editor", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    const triggerInput = await screen.findByRole("textbox", { name: "New trigger phrase for topic 1" });
    const addPhrase = (await screen.findAllByRole("button", { name: "Add phrase" }))[0];
    act(() => {
      for (let index = 0; index < 14; index += 1) {
        fireEvent.change(triggerInput, { target: { value: `phrase-${index}` } });
        fireEvent.click(addPhrase);
      }
    });
    fireEvent.change(triggerInput, { target: { value: "phrase-14" } });
    expect(addPhrase).not.toBeDisabled();
    fireEvent.click(addPhrase);
    expect(addPhrase).toBeDisabled();
  });

  it("renders connector validation errors as line items and metadata on success", async () => {
    connectorStatus = 422;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Validate definition" }));
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("definition must use OpenAPI 2.0");
    expect(error.querySelectorAll("li")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Retry validate" })).toBeInTheDocument();

    connectorStatus = null;
    fireEvent.click(screen.getByRole("button", { name: "Retry validate" }));
    expect(await screen.findByText("api.example.com")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Operations" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Security definitions" })).toBeInTheDocument();
  });

  it("generates connector metadata and downloads the response JSON", async () => {
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:connector");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(window.URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(window.URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Generate metadata" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download connector JSON" }));

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:connector");
    expect(anchorClick).toHaveBeenCalled();
    const downloaded = createObjectURL.mock.calls[0][0] as Blob;
    expect(JSON.parse(await downloaded.text())).toMatchObject({ connector_id: "customer-api", host: "api.example.com" });
    anchorClick.mockRestore();
  });
});
