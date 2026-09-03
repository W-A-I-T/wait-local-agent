import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Workflows } from "../src/screens/Workflows";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, isAdmin: true, selectedClientId: "acme", clients: [], isMspAdmin: false })
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
            id: "stale-ticket-sweep-review",
            name: "Stale Ticket Sweep Review",
            trigger: "schedule.daily",
            description: "Review stale tickets.",
            action_type: "ticket.stale_sweep",
            approval_required: false,
            risk_level: "low",
            preview_fields: [],
            tool_id: "stale-ticket-sweep",
            payload_schema: {
              type: "object",
              required: ["stale_after_minutes"],
              properties: { stale_after_minutes: "positive integer" }
            }
          },
          {
            id: "ticket-triage",
            name: "Ticket Triage",
            trigger: "ticket.created",
            description: "Classify tickets.",
            action_type: "ticket.triage",
            approval_required: false,
            risk_level: "low",
            preview_fields: []
          }
        ]), { status: 200 }));
      }
      if (path === "/workflows/templates/stale-ticket-sweep-review/runs") {
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

    await screen.findByRole("option", { name: "Stale Ticket Sweep Review" });
    fireEvent.change(screen.getByLabelText("Template"), { target: { value: "stale-ticket-sweep-review" } });
    fireEvent.change(screen.getByLabelText("Ticket id"), { target: { value: "TCK-1" } });
    fireEvent.change(screen.getByLabelText("Stale after minutes"), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Start Workflow" }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/workflows/templates/stale-ticket-sweep-review/runs",
      expect.objectContaining({
        body: JSON.stringify({
          template_id: "stale-ticket-sweep-review",
          ticket_id: "TCK-1",
          client_id: "acme",
          payload: { stale_after_minutes: 30 }
        })
      })
    ));
  });

  it("round-trips structured workflow fields through the raw JSON fallback", async () => {
    render(<MemoryRouter><Workflows /></MemoryRouter>);

    await screen.findByRole("option", { name: "Stale Ticket Sweep Review" });
    fireEvent.change(screen.getByLabelText("Template"), { target: { value: "stale-ticket-sweep-review" } });
    fireEvent.change(screen.getByLabelText("Stale after minutes"), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Raw JSON (advanced)" }));

    const raw = screen.getByLabelText("Raw JSON");
    expect((raw as HTMLTextAreaElement).value).toContain('"stale_after_minutes": 30');
    fireEvent.change(raw, { target: { value: '{"stale_after_minutes":45}' } });
    fireEvent.click(screen.getByRole("button", { name: "Back to form" }));

    expect(screen.getByLabelText("Stale after minutes")).toHaveValue(45);
  });

  it("shows the no-fields state and blocks missing required inputs", async () => {
    render(<MemoryRouter><Workflows /></MemoryRouter>);

    await screen.findByRole("option", { name: "Stale Ticket Sweep Review" });
    fireEvent.change(screen.getByLabelText("Template"), { target: { value: "stale-ticket-sweep-review" } });
    fireEvent.change(screen.getByLabelText("Ticket id"), { target: { value: "TCK-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Start Workflow" }));

    expect(await screen.findByText("Stale after minutes is required.")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/runs"))).toBe(false);

    fireEvent.change(screen.getByLabelText("Template"), { target: { value: "ticket-triage" } });
    expect(screen.getByText("No additional fields required.")).toBeInTheDocument();
  });
});
