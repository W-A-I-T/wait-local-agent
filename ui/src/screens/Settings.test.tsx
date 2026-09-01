import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Settings } from "./Settings";

const dashboardState = vi.hoisted(() => ({
  authState: "demo" as "demo" | "authenticated",
  isAdmin: true,
  loading: false,
  role: "admin" as "admin" | "viewer"
}));

vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => dashboardState
}));

afterEach(() => {
  dashboardState.authState = "demo";
  dashboardState.isAdmin = true;
  dashboardState.loading = false;
  dashboardState.role = "admin";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Settings loading", () => {
  it("keeps successful settings visible when demo mode forbids the secrets listing", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") {
        return jsonResponse({ local_model_provider: "llama.cpp", vector_backend: "local" });
      }
      if (path === "/settings/security") {
        return jsonResponse({ api_token_configured: false, demo_mode: true });
      }
      if (path === "/packs") {
        return jsonResponse([{ name: "Core pack", version: "1.2.3", locked: true, requires_license: false }]);
      }
      if (path === "/secrets") {
        return jsonResponse({ detail: "Secrets are unavailable in demo mode." }, 403);
      }
      if (path === "/update-status") {
        return jsonResponse({ status: "current", detail: "Current" });
      }
      if (path === "/founder/lp-status") {
        return jsonResponse({ error: "launch passport not configured" }, 409);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("Settings loaded.")).toBeInTheDocument();
    expect(screen.getByText("Provider mode").parentElement).toHaveTextContent("llama.cpp");
    expect(screen.getByText("Demo mode").parentElement).toHaveTextContent("enabled");
    expect(screen.getByText("Update check").parentElement).toHaveTextContent("current");
    expect(screen.getByText("Core pack")).toBeInTheDocument();
    expect(screen.getByText("unavailable in demo mode")).toBeInTheDocument();
    expect(screen.getByText("Vault contents are unavailable in demo mode.")).toBeInTheDocument();
    expect(screen.queryByText(/Administrator role required for admin settings/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(expect.arrayContaining([
      "/settings/providers",
      "/settings/security",
      "/packs",
      "/secrets",
      "/update-status",
      "/founder/lp-status"
    ]));
  });

  it("keeps the role-required message for a real security permission failure", async () => {
    dashboardState.authState = "authenticated";
    dashboardState.isAdmin = false;
    dashboardState.role = "viewer";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/security") {
        return jsonResponse({ detail: "forbidden" }, 403);
      }
      if (path === "/settings/providers") {
        return jsonResponse({ local_model_provider: "llama.cpp", vector_backend: "local" });
      }
      if (path === "/packs" || path === "/secrets") {
        return jsonResponse([]);
      }
      if (path === "/update-status") {
        return jsonResponse({ status: "current", detail: "Current" });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("Administrator role required for admin settings. Current role: viewer.")).toBeInTheDocument();
  });

  it("preserves the populated Vault state when secrets are available", async () => {
    dashboardState.authState = "authenticated";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({ local_model_provider: "llama.cpp", vector_backend: "local" });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: false, demo_mode: false });
      if (path === "/packs") return jsonResponse([]);
      if (path === "/secrets") return jsonResponse([{ key: "WAIT_API_KEY", configured: true, required_for: "Provider" }]);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/founder/lp-status") return jsonResponse({ error: "launch passport not configured" }, 409);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("WAIT_API_KEY")).toBeInTheDocument();
    expect(screen.getByText("1 keys")).toBeInTheDocument();
    expect(screen.queryByText(/unavailable in demo mode/)).not.toBeInTheDocument();
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
