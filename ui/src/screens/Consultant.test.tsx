import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Consultant } from "./Consultant";

vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, clientId: "acme" }),
}));

describe("Consultant architecture decisions", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      const responses: Record<string, unknown> = {
        "/consultant/blueprints": [{
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
});
