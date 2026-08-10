import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Connectors } from "../src/screens/Connectors";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({
    connectors: [{ id: "syncro", name: "Syncro", status: "ready", message: "configured" }],
    haloConnector: { status: "blocked", message: "not configured" },
    huduConnector: { status: "blocked", message: "not configured" },
    writeHealth: { status: "blocked", message: "writes disabled" },
    loading: false
  })
}));

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("Connectors screen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/connectors/halopsa/health" || path === "/connectors/halopsa/write-health" ||
          path === "/connectors/connectwise/health" || path === "/connectors/connectwise/write-health" ||
          path === "/connectors/hudu/health") {
        return json({ status: "blocked", message: "not configured" });
      }
      if (path === "/connectors/hudu/companies" || path === "/connectors/hudu/articles") {
        return json({ result: { count: 0 }, items: [] });
      }
      if (path.includes("/connectors/syncro/tickets/42/comments?page=2&per_page=10")) {
        return json({
          result: { status: "ready", message: "Syncro ticket comments read succeeded.", count: 1 },
          items: [{
            id: "comment-1",
            ticket_id: "42",
            created_at: "2026-08-10T08:00:00Z",
            updated_at: "2026-08-10T08:00:00Z",
            subject: "Internal review",
            body: "Reviewed locally",
            tech: "Taylor",
            hidden: true
          }],
          meta: { total_pages: 3, page: 2, per_page: 10 }
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("loads bounded Syncro comment history through the dashboard", async () => {
    render(<Connectors />);

    fireEvent.change(screen.getByLabelText("Ticket ID"), { target: { value: "42" } });
    fireEvent.change(screen.getByLabelText("Page"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Load comments" }));

    expect(await screen.findByText("Reviewed locally")).toBeInTheDocument();
    expect(screen.getByText("internal")).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3.")).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/connectors/syncro/tickets/42/comments?page=2&per_page=10",
      expect.anything()
    ));
  });

  it("rejects unsafe Syncro ticket input before making a request", async () => {
    render(<Connectors />);

    fireEvent.change(screen.getByLabelText("Ticket ID"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Load comments" }));

    expect(await screen.findByText("Enter a positive numeric Syncro ticket ID and page.")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/connectors/syncro/tickets/"))).toBe(false);
  });
});
