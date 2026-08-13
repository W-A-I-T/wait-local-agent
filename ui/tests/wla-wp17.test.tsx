import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Settings } from "../src/screens/Settings";
import { FounderJourney } from "../src/surfaces/founder/FounderJourney";

const dashboardState = vi.hoisted(() => ({ loading: false, role: "admin" as "admin" | "viewer" }));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({
    isAdmin: dashboardState.role === "admin",
    loading: dashboardState.loading,
    role: dashboardState.role
  })
}));

afterEach(() => {
  dashboardState.loading = false;
  dashboardState.role = "admin";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("wla-wp17 Launch Passport UI", () => {
  it("shows the optional, not-configured connection state without treating it as a failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({ local_model_provider: "local", vector_backend: "local" });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: false, demo_mode: true });
      if (path === "/packs" || path === "/secrets") return jsonResponse([]);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/founder/lp-status") return jsonResponse({ error: "launch passport not configured" }, 409);
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByText(/ready to use on its own/i)).toBeInTheDocument();
    expect(screen.queryByText(/temporarily unavailable/i)).not.toBeInTheDocument();
  });

  it("presents a connected project without remote launch as upload only", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({ local_model_provider: "local", vector_backend: "local" });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: false, demo_mode: true });
      if (path === "/packs" || path === "/secrets") return jsonResponse([]);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/founder/lp-status") return jsonResponse({ status: "connected", lp_project_id: "project-1", token_configured: true, capabilities: {} });
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("Upload only")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
  });

  it("checks model provider health only when the admin asks", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({
        local_model_provider: "local",
        provider_scope: "appliance-wide",
        context_scope: "tenant-scoped",
        vector_backend: "local"
      });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: false, demo_mode: true });
      if (path === "/packs" || path === "/secrets") return jsonResponse([]);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/founder/lp-status") return jsonResponse({ error: "launch passport not configured" }, 409);
      if (path === "/settings/providers/health") return jsonResponse({
        local: { provider: "local", model: "llama3.1", status: "ready", probe: "models", model_available: true },
        remote: { provider: null, model: null, status: "not_configured", probe: "not_run" }
      });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByRole("button", { name: "Check model health" })).toBeInTheDocument();
    expect(screen.getByText("Provider scope").parentElement).toHaveTextContent("appliance-wide");
    expect(screen.getByText("Request context").parentElement).toHaveTextContent("tenant-scoped");
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain("/settings/providers/health");
    fireEvent.click(screen.getByRole("button", { name: "Check model health" }));
    expect(await screen.findByText(/Local: ready/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain("/settings/providers/health");
  });

  it("does not request the admin-only project status for a viewer", async () => {
    dashboardState.role = "viewer";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({ local_model_provider: "local", vector_backend: "local" });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: false, demo_mode: true });
      if (path === "/packs" || path === "/secrets") return jsonResponse([]);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText(/Only administrators can view this project connection/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain("/founder/lp-status");
  });

  it("waits for the admin role to resolve before requesting project status", async () => {
    dashboardState.loading = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({ local_model_provider: "local", vector_backend: "local" });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: false, demo_mode: true });
      if (path === "/packs" || path === "/secrets") return jsonResponse([]);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/founder/lp-status") return jsonResponse({ status: "connected", token_configured: true, capabilities: {} });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("Settings loaded.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain("/founder/lp-status");

    dashboardState.loading = false;
    rerender(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("Upload only")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain("/founder/lp-status");
  });

  it("requires a preview before upload and turns a server refusal into clear guidance", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/founder/scan") return jsonResponse({ artifact_id: "art-1", status: "preview_ready" });
      if (path === "/founder/upload-preview/art-1") {
        return jsonResponse({ artifact_id: "art-1", file_count: 3, dependency_count: 2, finding_count: 1, env_key_names: ["PUBLIC_NAME"] });
      }
      if (path === "/founder/upload/art-1") return jsonResponse({ error: "fresh preview required" }, 409);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><FounderJourney /></MemoryRouter>);

    fireEvent.change(screen.getByPlaceholderText("/path/to/your-project"), { target: { value: "/workspace/project" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("What will be shared")).toBeInTheDocument();
    expect(screen.getByText("Source files are not uploaded.")).toBeInTheDocument();
    expect(screen.getByText(/Environment values are excluded/)).toBeInTheDocument();
    expect(screen.getByText(/Review the evidence summary before sending/)).toBeInTheDocument();
    expect(screen.queryByText(/No source code, secret values, or connector credentials/)).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith("/founder/upload/art-1", expect.anything());

    expect(screen.getByRole("button", { name: "Continue to confirmation" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview upload package" }));
    await screen.findByText("Review complete. You can now confirm this exact upload package.");
    expect(screen.getByRole("button", { name: "Continue to confirmation" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Continue to confirmation" }));
    expect(await screen.findByRole("heading", { name: "Confirm this upload" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Upload reviewed package" }));

    expect(await screen.findByText(/Review this upload package again/)).toBeInTheDocument();
    expect(screen.getByText("What will be shared")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue to confirmation" })).toBeDisabled();
  });

  it("shows results after a reviewed package is confirmed", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/founder/scan") return jsonResponse({ artifact_id: "art-1", status: "preview_ready" });
      if (path === "/founder/upload-preview/art-1") return jsonResponse({ artifact_id: "art-1", file_count: 3, dependency_count: 2, finding_count: 1 });
      if (path === "/founder/upload/art-1") return jsonResponse({ status: "uploaded" });
      if (path === "/founder/lp-status") return jsonResponse({ status: "connected", lp_project_id: "project-1" });
      if (path === "/founder/results") return jsonResponse({ project_id: "project-1", scans: [{}], latest_report: { id: "report-1" } });
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<MemoryRouter><FounderJourney /></MemoryRouter>);

    fireEvent.change(screen.getByPlaceholderText("/path/to/your-project"), { target: { value: "/workspace/project" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("What will be shared");
    fireEvent.click(screen.getByRole("button", { name: "Preview upload package" }));
    await screen.findByText("Review complete. You can now confirm this exact upload package.");
    fireEvent.click(screen.getByRole("button", { name: "Continue to confirmation" }));
    await screen.findByRole("heading", { name: "Confirm this upload" });
    fireEvent.click(screen.getByRole("button", { name: "Upload reviewed package" }));

    expect(await screen.findByRole("heading", { name: "Results" })).toBeInTheDocument();
    expect(screen.getByText(/latest report reference is available/i)).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("handles object-enveloped scan results without rendering an undefined count", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/founder/scan") return jsonResponse({ artifact_id: "art-1", status: "preview_ready" });
      if (path === "/founder/upload-preview/art-1") return jsonResponse({ artifact_id: "art-1" });
      if (path === "/founder/upload/art-1") return jsonResponse({ status: "uploaded" });
      if (path === "/founder/lp-status") return jsonResponse({ status: "connected", lp_project_id: "project-1" });
      if (path === "/founder/results") return jsonResponse({ project_id: "project-1", scans: { items: [{ id: "scan-1" }] } });
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<MemoryRouter><FounderJourney /></MemoryRouter>);

    fireEvent.change(screen.getByPlaceholderText("/path/to/your-project"), { target: { value: "/workspace/project" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("What will be shared");
    fireEvent.click(screen.getByRole("button", { name: "Preview upload package" }));
    await screen.findByText("Review complete. You can now confirm this exact upload package.");
    fireEvent.click(screen.getByRole("button", { name: "Continue to confirmation" }));
    await screen.findByRole("heading", { name: "Confirm this upload" });
    fireEvent.click(screen.getByRole("button", { name: "Upload reviewed package" }));

    expect(await screen.findByText("1 scan record available.")).toBeInTheDocument();
    expect(screen.queryByText(/undefined scan records available/i)).not.toBeInTheDocument();
  });

  it("does not store or render token echoes and maps unknown upstream states generically", async () => {
    const token = "launch-passport-token";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/founder/scan") return jsonResponse({ artifact_id: "art-1", status: token });
      if (path === "/founder/upload-preview/art-1") return jsonResponse({ artifact_id: "art-1" });
      if (path === "/founder/upload/art-1") return jsonResponse({ status: token, message: token });
      if (path === "/founder/lp-status") return jsonResponse({ status: "not-a-real-state", lp_project_id: token });
      if (path === "/founder/results") {
        return jsonResponse({
          project_id: token,
          scans: [{ status: token, message: token }],
          latest_report: { message: token }
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<MemoryRouter><FounderJourney /></MemoryRouter>);

    fireEvent.change(screen.getByPlaceholderText("/path/to/your-project"), { target: { value: "/workspace/project" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("What will be shared");
    fireEvent.click(screen.getByRole("button", { name: "Preview upload package" }));
    await screen.findByText("Review complete. You can now confirm this exact upload package.");
    fireEvent.click(screen.getByRole("button", { name: "Continue to confirmation" }));
    await screen.findByRole("heading", { name: "Confirm this upload" });
    fireEvent.click(screen.getByRole("button", { name: "Upload reviewed package" }));

    expect(await screen.findByRole("heading", { name: "Results" })).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(token);
  });

  it("does not render founder controls for a non-admin role", () => {
    dashboardState.role = "viewer";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><FounderJourney /></MemoryRouter>);

    expect(screen.getByText(/Administrator access is required/i)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("/path/to/your-project")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
