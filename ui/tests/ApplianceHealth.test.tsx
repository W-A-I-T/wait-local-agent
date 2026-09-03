import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApplianceHealth } from "../src/screens/ApplianceHealth";
import { Sidebar } from "../src/app/Sidebar";

const dashboard = vi.hoisted(() => ({
  isAdmin: true,
  role: "admin" as "admin" | "viewer",
  roleResolved: true
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

const health = {
  status: "ok",
  write_actions_enabled: false,
  http_probing_enabled: true,
  cloud_fallback_enabled: false,
  offline_mode: true,
  llm_inference_enabled: true,
  api_auth_required: true,
  demo_mode: false,
  secrets_backend: "local",
  scheduler_enabled: true,
  halopsa_configured: true,
  hudu_configured: false,
  syncro_configured: false,
  servicenow_configured: false,
  autotask_configured: false,
  itglue_configured: false,
  confluence_configured: false,
  sharepoint_configured: true,
  m365_configured: false
};

const scheduledBackupStatus = {
  items: [{ backup_run_id: 11, started_at: "2026-09-01T09:00:00Z", finished_at: "2026-09-01T09:00:02Z", status: "succeeded", destination: "backups/state.db.enc", size_bytes: 1024, failure_summary: "" }],
  page: 1,
  page_size: 25,
  total: 1,
  schedule_configured: true,
  schedule: null,
  last_restore_exercise: null
};

afterEach(() => {
  dashboard.isAdmin = true;
  dashboard.role = "admin";
  dashboard.roleResolved = true;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Appliance Health wiring", () => {
  it("loads and renders all read-only appliance sources", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/health") return jsonResponse(health);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "No update available.", version: "2.0.0" });
      if (path === "/hardening/runs") {
        return jsonResponse([{
          id: 12,
          status: "completed",
          started_at: "2026-08-15T10:00:00Z",
          completed_at: "2026-08-15T10:01:00Z",
          expected_check_count: 8,
          result_count: 8,
          results: []
        }]);
      }
      if (path === "/backups") return jsonResponse(scheduledBackupStatus);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <ApplianceHealth />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByText("Appliance health refreshed.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Appliance health" })).toHaveAttribute("href", "/system/appliance-health");
    expect(screen.getByText("Write health").parentElement).toHaveTextContent("Disabled");
    expect(screen.getByText("HTTP probing").parentElement).toHaveTextContent("Enabled");
    expect(screen.getByText("LLM inference").parentElement).toHaveTextContent("Enabled");
    expect(screen.getByText("Secrets backend").parentElement).toHaveTextContent("local");
    expect(screen.getByText("HaloPSA").parentElement).toHaveTextContent("Configured");
    expect(screen.getByText("SharePoint").parentElement).toHaveTextContent("Configured");
    expect(screen.getByText("No update available.")).toBeInTheDocument();
    expect(screen.getByText("Run 12")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(
      expect.arrayContaining(["/health", "/update-status", "/hardening/runs", "/backups"])
    );
    expect(screen.getByLabelText("Latest backup run")).toHaveTextContent("Run 11");
  });

  it("refreshes through the same read-only endpoints", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/health") return jsonResponse(health);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/hardening/runs") return jsonResponse([]);
      if (path === "/backups") return jsonResponse(emptyBackupStatus());
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><ApplianceHealth /></MemoryRouter>);
    await screen.findByText("Appliance health refreshed.");
    screen.getByRole("button", { name: "Refresh" }).click();

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/health")).toHaveLength(2);
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/update-status")).toHaveLength(2);
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/hardening/runs")).toHaveLength(2);
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/backups")).toHaveLength(2);
    });
  });

  it("does not fetch appliance details or show the admin navigation entry to viewers", async () => {
    dashboard.isAdmin = false;
    dashboard.role = "viewer";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <ApplianceHealth />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByText("Administrator role required to view appliance health.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Appliance health" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("confirms one backup request and renders the persisted run details", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/health") return jsonResponse(health);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/hardening/runs") return jsonResponse([]);
      if (path === "/backups/run") {
        expect(init?.method).toBe("POST");
        return jsonResponse({ backup_run_id: 27, started_at: "2026-09-01T10:00:00Z", finished_at: "2026-09-01T10:00:02Z", status: "succeeded", destination: "backups/state.db.enc", size_bytes: 2048, failure_summary: "" });
      }
      if (path === "/backups") return jsonResponse({ items: [{ backup_run_id: 27, started_at: "2026-09-01T10:00:00Z", finished_at: "2026-09-01T10:00:02Z", status: "succeeded", destination: "backups/state.db.enc", size_bytes: 2048, failure_summary: "" }], page: 1, page_size: 25, total: 1, schedule_configured: false, schedule: null, last_restore_exercise: null });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><ApplianceHealth /></MemoryRouter>);
    await screen.findByText("Appliance health refreshed.");
    fireEvent.click(screen.getByRole("button", { name: "Run backup now" }));
    expect(screen.getByRole("alertdialog", { name: "Confirm backup run" })).toBeInTheDocument();
    const confirmButton = screen.getByRole("button", { name: "Confirm backup run" });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    expect(await screen.findByText("Backup run 27 recorded with status succeeded.")).toBeInTheDocument();
    expect(screen.getByLabelText("Latest backup run")).toHaveTextContent("Run 27");
    expect(screen.getByLabelText("Latest backup run")).toHaveTextContent("Size: 2.0 KB");
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/backups/run")).toHaveLength(1);
  });

  it("maps a backup permission failure to the standard request error", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/health") return jsonResponse(health);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/hardening/runs") return jsonResponse([]);
      if (path === "/backups") return jsonResponse(emptyBackupStatus());
      if (path === "/backups/run") return new Response(JSON.stringify({ detail: "not allowed" }), { status: 403 });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><ApplianceHealth /></MemoryRouter>);
    await screen.findByText("Appliance health refreshed.");
    fireEvent.click(screen.getByRole("button", { name: "Run backup now" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm backup run" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have permission to do that.");
  });

  it("shows an administrator note when backup history is forbidden", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/health") return jsonResponse(health);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/hardening/runs") return jsonResponse([]);
      if (path === "/backups") return new Response(JSON.stringify({ detail: "not allowed" }), { status: 403 });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><ApplianceHealth /></MemoryRouter>);

    expect(await screen.findByText("Administrator access required to view backup history.")).toBeInTheDocument();
    expect(screen.queryByText(/admin only/i)).not.toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("disables backup runs and explains the demo restriction", async () => {
    const demoHealth = { ...health, demo_mode: true };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/health") return jsonResponse(demoHealth);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "Current" });
      if (path === "/hardening/runs") return jsonResponse([]);
      if (path === "/backups") return jsonResponse(emptyBackupStatus());
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><ApplianceHealth /></MemoryRouter>);
    expect(await screen.findByText("Backup runs are unavailable in demo mode.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run backup now" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([input]) => String(input) === "/backups/run")).toBe(false);
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" }
  });
}

function emptyBackupStatus() {
  return {
    items: [],
    page: 1,
    page_size: 25,
    total: 0,
    schedule_configured: false,
    schedule: null,
    last_restore_exercise: null
  };
}
