import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Consultant } from "../src/screens/Consultant";

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
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("loads a blueprint and renders its read-only workflow design", async () => {
    render(<MemoryRouter><Consultant /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Consultant blueprints" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Employee onboarding/ }));

    expect(await screen.findByRole("heading", { name: "Employee onboarding" })).toBeInTheDocument();
    expect(screen.getByText("Read-only sequence preview from the stored blueprint.")).toBeInTheDocument();
    expect(screen.getByText("Validate manager")).toBeInTheDocument();
    expect(screen.getByText(/no execution or deployment is started/i)).toBeInTheDocument();
  });
});
