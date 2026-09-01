import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiagnosticsSupport } from "../DiagnosticsSupport";
import { useDashboard } from "../../app/DashboardContext";

vi.mock("../../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedUseDashboard = vi.mocked(useDashboard);

const summary = {
  system: {
    version: "2.0.0-dev.0",
    build_commit: "abc123",
    update_channel_configured: false,
    os_name: "Linux",
    install_mode: "docker",
    surface_mode: "api_and_cli",
    free_disk_bytes: 1000,
    process_started_at: "2026-08-23T00:00:00Z",
    uptime_seconds: 30
  },
  configuration: {
    write_actions_enabled: false,
    http_probing_enabled: false,
    cloud_fallback_enabled: false,
    offline_mode: true,
    llm_inference_enabled: false,
    api_auth_required: true,
    demo_mode: false,
    scheduler_enabled: true,
    secrets_backend: "env",
    paths: {}
  },
  database: { schema_version: null, integrity_check: "ok" },
  connectors: [{ id: "halopsa", readiness: "configured" }],
  packs: [],
  failed_executions: [{
    run_kind: "workflow",
    status: "failed",
    started_at: "2026-08-23T00:00:00Z",
    finished_at: "2026-08-23T00:00:01Z",
    trigger_source: "api",
    steps: [{ kind: "workflow.template", name: "triage", status: "failed", error: "redacted error" }]
  }],
  audit_events: [],
  hardening: { status: "completed", expected_check_count: 4, result_count: 4 },
  update_status: { status: "not_checked", detail: "offline", configured: false },
  correlation_ids: [],
  support_upload: { configured: false, available: false }
};

describe("Diagnostics and support screen", () => {
  beforeEach(() => {
    mockedUseDashboard.mockReturnValue({ isAdmin: true, role: "admin", roleResolved: true } as never);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads safe status and previews inclusions and exclusions before download", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/diagnostics/summary") return jsonResponse(summary);
      if (path === "/packs/status") return jsonResponse([]);
      if (path === "/diagnostics/bundle/preview") {
        return jsonResponse({ inclusions: ["system", "connectors"], exclusions: ["ticket bodies", "keys and tokens"] });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DiagnosticsSupport />);

    expect(await screen.findByText("Diagnostics refreshed.")).toBeInTheDocument();
    expect(screen.getByText("2.0.0-dev.0")).toBeInTheDocument();
    expect(screen.getByText(/redacted error/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate diagnostic bundle" }));

    expect(await screen.findByText("ticket bodies")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    expect(screen.getByText("Upload is unavailable while this appliance is offline.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(
      expect.arrayContaining(["/diagnostics/summary", "/packs/status", "/diagnostics/bundle/preview"])
    );
  });

  it("shows the administrator fallback and never fetches for a viewer", async () => {
    mockedUseDashboard.mockReturnValue({ isAdmin: false, role: "viewer", roleResolved: true } as never);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<DiagnosticsSupport />);

    expect(await screen.findByText("Administrator role required to view appliance diagnostics.")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { headers: { "Content-Type": "application/json" } });
}
