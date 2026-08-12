import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Consultant } from "../src/screens/Consultant";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true })
}));

describe("Consultant", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/consultant/blueprints") {
        return Promise.resolve(new Response(JSON.stringify([{
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
      if (path === "/consultant/discovery") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait-local-agent.solution-discovery",
          format_version: 1,
          client_id: "acme",
          missing_required: [],
          readiness: "ready_for_architecture",
          risk_review: { level: "medium", factors: [], evidence_only: true },
          roi_analysis: { status: "needs_estimates" },
          blueprint_candidate: {},
          inference_started: false,
          execution_started: false,
          deployment_started: false
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
    fireEvent.change(screen.getByLabelText("Business goal"), { target: { value: "Reduce onboarding effort" } });
    fireEvent.click(screen.getByRole("button", { name: "Assess discovery" }));
    expect(await screen.findByText(/Ready for architecture review/i)).toBeInTheDocument();
  });
});
