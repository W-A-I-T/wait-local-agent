import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { McpIntegration } from "../src/screens/McpIntegration";

const dashboard = vi.hoisted(() => ({
  role: "admin" as "admin" | "viewer",
  roleResolved: true
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("MCP integration screen", () => {
  beforeEach(() => {
    dashboard.role = "admin";
    dashboard.roleResolved = true;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/mcp") {
        return new Response(null, { status: 405, headers: { Allow: "POST" } });
      }
      if (path === "/tools") {
        return json([{
          id: "ticket.read",
          name: "Read ticket",
          description: "Read a tenant-scoped ticket.",
          risk_level: "low",
          required_role: "technician",
          approval_required: false,
          access_mode: "read"
        }]);
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("loads the live catalog from the existing MCP endpoints", async () => {
    render(<McpIntegration />);

    expect(await screen.findByRole("heading", { name: "Read ticket" })).toBeInTheDocument();
    expect(screen.getByText("Read a tenant-scoped ticket.")).toBeInTheDocument();
    expect(screen.getByText("2025-11-25")).toBeInTheDocument();
    expect(screen.getAllByText(/POST \/mcp/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Authorization: Bearer/)).toBeInTheDocument();

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/mcp", expect.anything());
      expect(fetch).toHaveBeenCalledWith("/tools", expect.anything());
    });
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init && typeof init === "object" && "method" in init && init.method === "POST")).toBe(false);
  });

  it("does not fetch MCP details for a non-admin", () => {
    dashboard.role = "viewer";

    render(<McpIntegration />);

    expect(screen.getByRole("heading", { name: "MCP integrations" })).toBeInTheDocument();
    expect(screen.getByText(/Administrator role required/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});
