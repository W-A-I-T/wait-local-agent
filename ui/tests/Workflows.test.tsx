import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Workflows } from "../src/screens/Workflows";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, isAdmin: true })
}));

describe("Workflows", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/workflow-runs") {
        return Promise.resolve(new Response(JSON.stringify([
          { id: 1, template_id: "ticket-triage", ticket_id: "TCK-1", status: "failed", message: "old" },
          { id: 2, template_id: "ticket-triage", ticket_id: "TCK-1", status: "completed", message: "new" }
        ]), { status: 200 }));
      }
      if (path === "/workflows/templates") {
        return Promise.resolve(new Response(JSON.stringify([
          {
            id: "ticket-sla-risk-review",
            name: "Ticket SLA Risk Review",
            trigger: "schedule.daily",
            description: "Review ticket age.",
            action_type: "ticket.sla_assessment",
            approval_required: false,
            risk_level: "low",
            preview_fields: [],
            tool_id: "ticket-sla-assessment",
            payload_schema: {
              type: "object",
              required: ["thresholds_minutes"],
              properties: { thresholds_minutes: "object" }
            }
          }
        ]), { status: 200 }));
      }
      if (path === "/workflows/templates/ticket-sla-risk-review/runs") {
        return Promise.resolve(new Response(JSON.stringify({ id: 3, status: "completed" }), { status: 200 }));
      }
      if (path === "/workflow-runs/1/compare/2") {
        return Promise.resolve(new Response(JSON.stringify({
          from_run: { id: 1 },
          to_run: { id: 2 },
          changed: true,
          changes: [{ field: "status", before: "failed", after: "completed" }]
        }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("compares two workflow runs from the dashboard", async () => {
    render(<MemoryRouter><Workflows /></MemoryRouter>);

    expect((await screen.findAllByText("Run 1")).length).toBe(2);
    fireEvent.change(screen.getByLabelText("From run"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("To run"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare runs" }));

    await waitFor(() => expect(screen.getByText("status")).toBeInTheDocument());
    expect((screen.getAllByText(/failed/)).length).toBeGreaterThan(0);
    expect((screen.getAllByText(/completed/)).length).toBeGreaterThan(0);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/workflow-runs/1/compare/2",
      expect.objectContaining({ headers: expect.anything() })
    );
  });

  it("submits the selected template payload through the workflow UI", async () => {
    render(<MemoryRouter><Workflows /></MemoryRouter>);

    await screen.findByRole("option", { name: "Ticket SLA Risk Review" });
    fireEvent.change(screen.getByLabelText("Template"), { target: { value: "ticket-sla-risk-review" } });
    fireEvent.change(screen.getByLabelText("Ticket id"), { target: { value: "TCK-1" } });
    fireEvent.change(screen.getByLabelText("Template payload JSON"), {
      target: { value: '{"thresholds_minutes":{"high":1}}' }
    });
    fireEvent.click(screen.getByRole("button", { name: "Start Workflow" }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/workflows/templates/ticket-sla-risk-review/runs",
      expect.objectContaining({
        body: JSON.stringify({
          template_id: "ticket-sla-risk-review",
          ticket_id: "TCK-1",
          client_id: undefined,
          payload: { thresholds_minutes: { high: 1 } }
        })
      })
    ));
  });
});
