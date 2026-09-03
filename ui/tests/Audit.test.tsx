import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Audit } from "../src/screens/Audit";
import { MemoryRouter } from "react-router-dom";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({
    clients: [{ client_id: "acme", name: "Acme Support", status: "active" }]
  })
}));

describe("Audit export filters", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/audit") return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      if (path.startsWith("/audit-events/export?")) return Promise.resolve(new Response("id,event_type\n", { status: 200 }));
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("sends format and date range parameters to the audit export route", async () => {
    render(<MemoryRouter><Audit /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Audit" });
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-08-08" } });
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/audit-events/export?format=csv&from=2026-08-01T00%3A00%3A00Z&to=2026-08-08T23%3A59%3A59Z",
      expect.anything()
    ));
  });

  it("filters by approval subject and links events to a supplied run", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/audit") return Promise.resolve(new Response(JSON.stringify([{
        id: 10,
        event_type: "approval.executed",
        subject_id: "subject-1",
        status: "succeeded",
        message: "Action completed",
        created_at: "2026-08-08T00:00:00Z",
        execution_id: 42
      }, {
        id: 11,
        event_type: "other",
        subject_id: "subject-2",
        status: "ok",
        message: "Other event"
      }]), { status: 200 }));
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<MemoryRouter initialEntries={["/audit?subject=subject-1"]}><Audit /></MemoryRouter>);

    expect(await screen.findByText("Action completed")).toBeInTheDocument();
    expect(screen.queryByText("Other event")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open related run" })).toHaveAttribute("href", "/executions/42?kind=execution");
  });
});
