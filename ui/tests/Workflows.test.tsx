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
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
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
});
