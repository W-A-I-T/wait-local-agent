import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Analytics } from "../src/screens/Analytics";

describe("Analytics", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      range: { from: null, to: null },
      client_id: "acme",
      executions_over_time: [],
      success_rate: { total: 4, succeeded: 3, rate: 0.75 },
      failures_by_status: [{ status: "failed", count: 1 }],
      activity_breakdown: [],
      approval_rate: {
        requested: 2,
        decided: 2,
        approved: 1,
        rejected: 1,
        pending: 0,
        rate: 0.5,
        derivation: "test"
      },
      ticket_metrics: {
        touched: 3,
        resolved: 2,
        resolution_rate: 2 / 3,
        derivation: "test"
      },
      activity_by_workflow: [{
        run_kind: "workflow",
        workflow_id: "ticket-triage",
        total: 4,
        succeeded: 3,
        status_counts: [{ status: "completed", count: 3 }, { status: "failed", count: 1 }]
      }],
      estimated_minutes_saved: { minutes: 12, estimate: true, derivation: "test" }
    }), { status: 200, headers: { "Content-Type": "application/json" } }))));
  });

  it("renders operator metrics and workflow activity", async () => {
    render(<MemoryRouter><Analytics /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getByText("75% successful")).toBeInTheDocument();
    expect(screen.getByText("Tickets resolved")).toBeInTheDocument();
    expect(screen.getByText("ticket-triage")).toBeInTheDocument();
    expect(screen.getByText("completed: 3 · failed: 1")).toBeInTheDocument();
    expect(screen.getByText("Estimated time saved")).toBeInTheDocument();
  });

  it("applies date and client filters through the tenant-scoped API", async () => {
    const fetchMock = vi.mocked(fetch);
    render(<MemoryRouter><Analytics /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Analytics" });
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-08-08" } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining("/analytics/summary?from=2026-08-01&to=2026-08-08&client_id=acme"),
      expect.anything(),
    ));
  });
});
