import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardProvider } from "../src/app/DashboardContext";
import { Reports } from "../src/screens/Reports";

describe("Dashboard authorization", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not expose evidence run actions before the role is resolved", async () => {
    let resolveRole: (response: Response) => void = () => undefined;
    const roleResponse = new Promise<Response>((resolve) => {
      resolveRole = resolve;
    });
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/auth/role") {
        return roleResponse;
      }
      if (path === "/reports" || path === "/hardening/runs" || path === "/backup/restore-exercises" || path === "/connectors") {
        return Promise.resolve(json([]));
      }
      if (path === "/settings/security" || path === "/settings/providers") {
        return Promise.resolve(json({}));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(
      <DashboardProvider>
        <Reports />
      </DashboardProvider>
    );

    expect(screen.getAllByText("Checking your access before actions are available.")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Run checks now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run a restore drill" })).not.toBeInTheDocument();

    resolveRole(json({ role: "admin", api_auth_required: false, demo_mode: true }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Run checks now" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Run a restore drill" })).toBeInTheDocument();
  });
});

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
