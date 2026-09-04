import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../src/app/Sidebar";
import { SmartActionCatalog } from "../src/screens/SmartActionCatalog";

const dashboard = vi.hoisted(() => ({
  role: "viewer" as "admin" | "viewer",
  roleResolved: true
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

const actions = [
  {
    action_id: "ticket-lookup",
    title: "Ticket lookup",
    description: "Read a tenant-scoped ticket.",
    kind: "deterministic",
    input_schema: { type: "object", properties: { ticket_id: { type: "string" } } },
    output_schema: { type: "object", properties: { ticket: { type: "object" } } },
    requires_approval: false,
    estimated_minutes_saved: 5,
    risk_level: "low",
    required_role: "viewer",
    access_mode: "read",
    approval_expiry_seconds: 900
  },
  {
    action_id: "user-offboarding",
    title: "User offboarding",
    description: "Prepare a governed user offboarding action.",
    kind: "ai_assisted",
    input_schema: { type: "object", required: ["user_id"] },
    output_schema: { type: "object" },
    requires_approval: true,
    estimated_minutes_saved: 20,
    risk_level: "high",
    required_role: "admin",
    access_mode: "write",
    approval_expiry_seconds: 3600
  }
];

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Smart Action catalog", () => {
  it("renders the catalog, filters by text, opens detail, and exposes viewer navigation", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/smart-actions") return jsonResponse(actions);
      if (String(input) === "/smart-actions/user-offboarding") return jsonResponse(actions[1]);
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <SmartActionCatalog />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByText("Ticket lookup")).toBeInTheDocument();
    expect(screen.getByText("User offboarding")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Automations" })).toHaveAttribute("href", "/workflows");

    fireEvent.change(screen.getByRole("searchbox", { name: "Search Smart Actions" }), { target: { value: "offboarding" } });
    expect(screen.queryByText("Ticket lookup")).not.toBeInTheDocument();
    expect(screen.getByText("User offboarding")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "User offboarding" }));
    expect(await screen.findByRole("heading", { name: "User offboarding" })).toBeInTheDocument();
    expect(screen.getByText(/"user_id"/)).toBeInTheDocument();
    expect(screen.getAllByText("Not declared by this manifest")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith("/smart-actions/user-offboarding", expect.anything());
  });

  it("shows the read-only error state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "catalog unavailable" }), { status: 503 })));

    render(<SmartActionCatalog />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Loading Smart Action catalog…")).not.toBeInTheDocument());
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" }
  });
}
