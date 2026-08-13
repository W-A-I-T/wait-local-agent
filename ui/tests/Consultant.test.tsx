import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Consultant } from "../src/screens/Consultant";

const dashboard = vi.hoisted(() => ({ clientId: "acme" }));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, clientId: dashboard.clientId })
}));

describe("Consultant", () => {
  let noBlueprints = false;

  beforeEach(() => {
    noBlueprints = false;
    dashboard.clientId = "acme";
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/consultant/blueprints") {
        return Promise.resolve(new Response(JSON.stringify(noBlueprints ? [] : [{
          id: "bp-acme",
          client_id: "acme",
          created_by: "architect",
          created_at: "2026-08-11T00:00:00Z",
          updated_at: "2026-08-11T00:00:00Z",
          solution: { name: "Employee onboarding" },
          risk: "medium",
          agents: [{ id: "onboarding", name: "Onboarding", purpose: "Coordinate onboarding", tools: [], knowledge: [] }],
          workflows: [{ id: "onboarding-flow", name: "Onboarding flow", trigger: "HR request", steps: ["Validate manager", "Prepare approval"] }]
        }]), { status: 200 }));
      }
      if (path === "/consultant/blueprints/bp-acme/architecture") {
        return Promise.resolve(new Response(JSON.stringify({
          blueprint_id: "bp-acme",
          client_id: "acme",
          solution: { name: "Employee onboarding" },
          risk: "medium",
          approval_policy: { licenses: "IT" },
          components: [
            { id: "onboarding", kind: "agent", name: "Onboarding", status: "ready", implementation: "existing_agent_runtime" },
            { id: "onboarding-flow", kind: "workflow", name: "Onboarding flow", status: "needs_review", implementation: "design_only", trigger: "HR request", steps: ["Validate manager", "Prepare approval"] }
          ],
          open_items: [{ kind: "workflow_template", component_id: "onboarding-flow", detail: "review" }],
          readiness: "needs_review",
          execution_started: false,
          deployment_started: false
        }), { status: 200 }));
      }
      if (path === "/consultant/use-cases") {
        return Promise.resolve(new Response(JSON.stringify({
          use_cases: [{
            id: "teams-ticket-triage",
            title: "Teams service-desk triage",
            category: "teams",
            business_goal: "Triage a request",
            services: ["Microsoft Teams"],
            agent_roles: ["supervisor"],
            outputs: ["approval preview"],
            approval_boundaries: ["message delivery"]
          }]
        }), { status: 200 }));
      }
      if (path === "/consultant/monitoring/agents") {
        return Promise.resolve(new Response(JSON.stringify({
          client_id: "acme",
          agent_count: 1,
          total_runs: 2,
          failed_runs: 0,
          failure_rate: 0,
          payloads_exposed: false
        }), { status: 200 }));
      }
      if (path === "/consultant/demos/employee-onboarding") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.employee-onboarding-demo",
          format_version: 1,
          client_id: "acme",
          entity_id: "TCK-1001",
          mode: "local_fixture",
          stages: {
            blueprint: { id: "bp-acme", solution_name: "Employee onboarding supervisor", risk: "high" },
            supervisor: { status: "completed", children: [] },
            evaluation: { production_readiness: "pass", execution_started: true },
            governance: { status: "needs_review" },
            artifacts: {
              status: "review_only",
              items: [{ format: "wait-local-agent.power-apps-artifact" }],
              package_digest: "sha256:fixture",
              deployment_package_generated: false,
            },
            delivery: { production_readiness: "needs_review", deployment_started: false },
          },
          boundaries: {
            live_provider_execution: false,
            artifact_generation: true,
            artifact_generation_status: "review_only",
            review_package_generated: true,
            deployable_package_generated: false,
            deployment_started: false,
            production_deployment_requires_approval: true,
            external_systems_require_environment_verification: true,
            sensitive_operations_require_human_approval: true,
          },
          audit: { audit_event_count: 32, agent_run_count: 8 },
        }), { status: 200 }));
      }
      if (path === "/consultant/workflows/power-automate/plan") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.power-automate-flow-plan",
          format_version: 1,
          client_id: "acme",
          workflow_id: "onboarding-flow",
          workflow_name: "Onboarding flow",
          power_automate: { trigger: { type: "manual_review_trigger", name: "HR request" }, actions: [] },
          requires_approval: false,
          credentials_included: false,
          execution_started: false,
          deployment_started: false,
          export_status: "review_only"
        }), { status: 200 }));
      }
      if (path === "/consultant/power-apps/build") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.power-apps-artifact",
          format_version: 1,
          client_id: "acme",
          app_name: "Employee onboarding workspace",
          solution: { unique_name: "wait_acme_employee_onboarding", publisher_prefix: "wait" },
          dataverse: { tables: [] },
          canvas_app: { screens: [], connector_references: [] },
          files: [
            { path: "dataverse/schema.json", media_type: "application/json", content: {} },
            { path: "canvas-app/manifest.json", media_type: "application/json", content: {} },
            { path: "README.md", media_type: "text/markdown", content: "review" },
          ],
          requires_approval: true,
          credentials_included: false,
          build_started: true,
          dataverse_write_started: false,
          execution_started: false,
          deployment_started: false,
          package_status: "review_only",
        }), { status: 200 }));
      }
      if (path === "/consultant/discovery") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.solution-discovery",
          format_version: 1,
          client_id: "acme",
          missing_required: [],
          readiness: "ready_for_architecture",
          risk_review: { level: "medium", factors: [], evidence_only: true },
          roi_analysis: { status: "needs_estimates" },
          answered: {
            solution_name: "Employee onboarding",
            business_goal: "Reduce onboarding effort",
            users: ["HR"],
            systems: ["Microsoft Entra"],
            knowledge: ["Employee handbook"],
            changes: ["Create user"],
            approvals: ["Create user"],
            failure_handling: "Pause for review",
            data_location: ["Tenant SharePoint"],
            data_leaves_tenant: false,
          },
          blueprint_candidate: { approvals: { "Create user": "human_review_required" } },
          inference_started: false,
          execution_started: false,
          deployment_started: false
        }), { status: 200 }));
      }
      if (path === "/consultant/discovery/promote") {
        return Promise.resolve(new Response(JSON.stringify({
          blueprint: {
            id: "bp-saved",
            client_id: "acme",
            created_by: "architect",
            created_at: "2026-08-12T00:00:00Z",
            updated_at: "2026-08-12T00:00:00Z",
            solution: { name: "Employee onboarding review" },
            risk: "medium",
            agents: [],
            workflows: [],
          },
          discovery: { missing_required: [], readiness: "ready_for_architecture" },
          execution_started: false,
          deployment_started: false,
        }), { status: 201 }));
      }
      if (path === "/consultant/discovery/sessions") {
        if (String(init?.method ?? "GET") === "GET") {
          return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
        }
        return Promise.resolve(new Response(JSON.stringify({
          session_id: "CDS-guided",
          principal_scope: "technician",
          transcript: [],
          turn_index: 0,
          next_question: { id: "users", prompt: "Who uses this?", kind: "list", required: true, answered: false },
          assistant_message: "Who uses this?",
          missing_required: ["users"],
          readiness: "needs_discovery",
          risk_review: { level: "medium", factors: [], evidence_only: true },
          roi_analysis: { status: "needs_estimates" },
          status: "active",
          inference_started: false,
          execution_started: false,
          deployment_started: false,
        }), { status: 200 }));
      }
      if (path === "/consultant/discovery/sessions/CDS-guided") {
        return Promise.resolve(new Response(JSON.stringify({
          session_id: "CDS-guided",
          principal_scope: "technician",
          transcript: [
            { role: "user", field: "business_goal", content: "We want to automate employee onboarding" },
            { role: "assistant", field: "users", content: "Who uses this?" },
          ],
          turn_index: 1,
          next_question: { id: "users", prompt: "Who uses this?", kind: "list", required: true, answered: false },
          assistant_message: "Who uses this?",
          answered: { business_goal: "We want to automate employee onboarding" },
          missing_required: ["users"],
          readiness: "needs_discovery",
          risk_review: { level: "medium", factors: [], evidence_only: true },
          roi_analysis: { status: "needs_estimates" },
          status: "active",
          inference_started: false,
          execution_started: false,
          deployment_started: false,
        }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("loads a blueprint and renders its read-only workflow design", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Consultant blueprints" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));

    expect(await screen.findByRole("heading", { name: "Employee onboarding" })).toBeInTheDocument();
    expect(screen.getByText(/Edit a bounded local draft before preparing the Power Automate review artifact/)).toBeInTheDocument();
    expect(screen.getByText("Validate manager")).toBeInTheDocument();
    expect(screen.getByText(/no execution or deployment is started/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Trigger"), { target: { value: "HR approval request" } });
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    expect(screen.getByDisplayValue("New action")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Consultant use cases" })).toBeInTheDocument();
    expect(screen.getByText("Teams service-desk triage")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prepare Power Automate plan" }));
    expect(await screen.findByText(/Power Automate plan ready for review/i)).toBeInTheDocument();
    const planCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/workflows/power-automate/plan");
    expect(planCall?.[1]).toMatchObject({
      body: expect.stringContaining('"workflow_id":"onboarding_flow"'),
    });
    fireEvent.click(screen.getByRole("button", { name: "Build local artifact" }));
    expect(await screen.findByText(/Power Apps artifact ready for review/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run local onboarding walkthrough" }));
    expect(await screen.findByText(/completed in local_fixture mode/i)).toBeInTheDocument();
    expect(screen.getByText(/Artifacts: 1 review-only/)).toBeInTheDocument();
    const onboardingCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/demos/employee-onboarding");
    expect(onboardingCall?.[1]).toMatchObject({
      body: expect.stringContaining('"blueprint_id":"bp-acme"'),
    });
    fireEvent.change(screen.getByLabelText("Business goal"), { target: { value: "Reduce onboarding effort" } });
    fireEvent.change(screen.getByLabelText("Solution name"), { target: { value: "Employee onboarding review" } });
    fireEvent.click(screen.getByRole("button", { name: "Assess discovery" }));
    expect(await screen.findByText(/Ready for architecture review/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save solution blueprint" }));
    expect(await screen.findByText(/saved for architecture review/i)).toBeInTheDocument();
    const promotionCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/discovery/promote");
    expect(promotionCall?.[1]).toMatchObject({
      body: expect.stringContaining('"solution_name":"Employee onboarding review"'),
    });
  });

  it("starts guided discovery from the authenticated tenant when no blueprint exists", async () => {
    noBlueprints = true;
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByText("No solution blueprints are available for this tenant.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Business goal"), { target: { value: "We want to automate employee onboarding" } });
    fireEvent.click(screen.getByRole("button", { name: "Start guided discovery" }));

    expect(await screen.findByText("Who uses this?")).toBeInTheDocument();
    const guidedCall = vi.mocked(fetch).mock.calls.find(([input, init]) => String(input) === "/consultant/discovery/sessions" && init?.method === "POST");
    expect(guidedCall?.[1]).toMatchObject({
      body: expect.stringContaining('"client_id":"acme"'),
    });
    expect(screen.getByText(/Saved sessions are visible only to this tenant/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /CDS-guided/ }));
    expect(await screen.findByRole("list", { name: "Guided discovery transcript" })).toHaveTextContent("We want to automate employee onboarding");
  });

  it("uses the entered workspace when the local demo has no authenticated tenant scope", async () => {
    noBlueprints = true;
    dashboard.clientId = "";
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByText("No solution blueprints are available for this tenant.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Customer workspace ID"), { target: { value: "acme-browser" } });
    fireEvent.change(screen.getByLabelText("Business goal"), { target: { value: "We want to automate employee onboarding" } });
    fireEvent.click(screen.getByRole("button", { name: "Assess discovery" }));

    expect(await screen.findByText(/Ready for architecture review/i)).toBeInTheDocument();
    const discoveryCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/consultant/discovery");
    expect(discoveryCall?.[1]).toMatchObject({
      body: expect.stringContaining('"client_id":"acme-browser"'),
    });
  });
});
