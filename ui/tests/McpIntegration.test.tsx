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
        return json({
          jsonrpc: "2.0",
          id: 1,
          result: {
            protocolVersion: "2025-11-25",
            capabilities: { tools: { listChanged: true } },
            serverInfo: { name: "live-wait", version: "3.0.0", description: "Live MCP server" }
          }
        });
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

  it("loads the live handshake and catalog from the MCP endpoints", async () => {
    render(<McpIntegration />);

    expect(await screen.findByRole("heading", { name: "Read ticket" })).toBeInTheDocument();
    expect(screen.getByText("Read a tenant-scoped ticket.")).toBeInTheDocument();
    expect(screen.getByText("2025-11-25")).toBeInTheDocument();
    expect(screen.getByText("Live MCP server")).toBeInTheDocument();
    expect(screen.getAllByText(/POST \/mcp/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Authorization: Bearer/)).toBeInTheDocument();

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/mcp", expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"method":"initialize"')
      }));
      expect(fetch).toHaveBeenCalledWith("/tools", expect.anything());
    });
  });

  it("shows an honest static summary when the live handshake is unavailable", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/mcp") return Promise.resolve(new Response(null, { status: 503 }));
      if (String(input) === "/tools") return Promise.resolve(json([]));
      throw new Error(`Unexpected request: ${String(input)}`);
    });

    render(<McpIntegration />);

    expect(await screen.findByText("Static capability summary (live handshake unavailable).")).toBeInTheDocument();
    expect(screen.getByText("2025-11-25")).toBeInTheDocument();
  });

  it("does not fetch MCP details for a non-admin", () => {
    dashboard.role = "viewer";

    render(<McpIntegration />);

    expect(screen.getByRole("heading", { name: "MCP integrations" })).toBeInTheDocument();
    expect(screen.getByText(/Administrator role required/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});
