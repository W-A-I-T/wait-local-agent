import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MicrosoftAdmin } from "./MicrosoftAdmin";

const dashboardContext = vi.hoisted(() => ({
  role: "technician" as "viewer" | "technician" | "admin",
  roleResolved: true,
  selectedClientId: "acme"
}));

vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => dashboardContext
}));

const dashboard = {
  generated_at: "2026-08-25T18:00:00Z",
  status: "partial",
  summary: {
    non_operational_services: 1,
    open_service_issues: 2,
    secure_score_percent: 62.5,
    failed_sign_ins: 4,
    risky_sign_ins: 2,
    risky_users: 1,
    conditional_access_policies: 7,
    conditional_access_disabled: 1,
    conditional_access_report_only: 2,
    managed_devices: 20,
    noncompliant_devices: 3,
    unencrypted_devices: 1,
    stale_devices: 2,
    intune_apps: 18,
    compliance_policies: 4,
    autopilot_devices: 12,
    active_defender_incidents: 2,
    high_severity_incidents: 1,
    active_defender_alerts: 5
  },
  recommendations: [
    {
      priority: "high",
      code: "intune-noncompliant-devices",
      summary: "Investigate noncompliant Intune devices before relaxing Conditional Access.",
      automatic_execution: false
    }
  ],
  source_statuses: {
    service_health: "ready",
    managed_devices: "failed"
  }
};

const runbooks = [
  {
    runbook_id: "windows.endpoint_health",
    version: "1.0.0",
    title: "Windows endpoint health",
    description: "Collect bounded Windows endpoint evidence.",
    effect: "read",
    risk_level: 1,
    timeout_seconds: 60,
    approval_required: true,
    script_sha256: "sha256:endpoint",
    parameters: [
      {
        name: "include_event_logs",
        kind: "boolean",
        description: "Include critical event metadata",
        default: true,
        minimum: null,
        maximum: null,
        choices: []
      },
      {
        name: "event_hours",
        kind: "integer",
        description: "Event lookback hours",
        default: 24,
        minimum: 1,
        maximum: 72,
        choices: []
      }
    ]
  },
  {
    runbook_id: "windows.service_restart",
    version: "1.0.0",
    title: "Restart an allowlisted Windows service",
    description: "Restart one explicitly allowlisted service.",
    effect: "write",
    risk_level: 3,
    timeout_seconds: 45,
    approval_required: true,
    script_sha256: "sha256:restart",
    parameters: [
      {
        name: "service_name",
        kind: "choice",
        description: "The fixed Windows service to restart.",
        default: "IntuneManagementExtension",
        minimum: null,
        maximum: null,
        choices: ["IntuneManagementExtension", "wuauserv", "BITS"]
      },
      {
        name: "wait_seconds",
        kind: "integer",
        description: "Maximum wait for Running.",
        default: 15,
        minimum: 1,
        maximum: 30,
        choices: []
      }
    ]
  }
];

const diagnostic = {
  user_identity: "adele@example.test",
  device_name: "LAPTOP-001",
  generated_at: "2026-08-25T18:05:00Z",
  evidence_completeness: 0.86,
  probable_root_cause: "Managed device LAPTOP-001 is not compliant.",
  findings: [
    {
      code: "device-noncompliant",
      severity: "high",
      summary: "Managed device LAPTOP-001 is not compliant.",
      evidence: { device_id: "device-1" },
      recommended_action: "Trigger an Intune sync, then re-evaluate compliance.",
      action_id: "m365-managed-device-sync",
      approval_required: true
    }
  ],
  source_statuses: { managed_devices: "ready" }
};

const remediations = [
  {
    action_id: "m365-managed-device-sync",
    risk_level: 2,
    approval_required: true,
    description: "Trigger an Intune managed-device synchronization through the core approval flow."
  }
];

describe("Microsoft Administrator workspace", () => {
  let failDashboard = false;
  let failDiagnostic = false;

  beforeEach(() => {
    failDashboard = false;
    failDiagnostic = false;
    dashboardContext.role = "technician";
    dashboardContext.roleResolved = true;
    dashboardContext.selectedClientId = "acme";
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/packs/microsoft-admin/dashboard") {
        if (failDashboard) return Promise.reject(new Error("Graph evidence unavailable"));
        return Promise.resolve(new Response(JSON.stringify(dashboard), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/runbooks") {
        return Promise.resolve(new Response(JSON.stringify(runbooks), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/runbooks/status") {
        return Promise.resolve(new Response(JSON.stringify({
          status: "ready",
          message: "PowerShell runbook execution prerequisites are ready.",
          executable: "C:/Program Files/PowerShell/7/pwsh.exe"
        }), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/remediations") {
        return Promise.resolve(new Response(JSON.stringify(remediations), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/identity/risky-users?page_size=25") {
        return Promise.resolve(new Response(JSON.stringify({
          result: { status: "ready", message: "ok", count: 1 },
          items: [{ id: "risky-1", user_display_name: "Adele Vance", user_principal_name: "adele@example.test", risk_level: "high", risk_state: "atRisk", risk_last_updated_date_time: "2026-08-25T17:00:00Z" }],
          next_cursor: ""
        }), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/security/incidents?page_size=25") {
        return Promise.resolve(new Response(JSON.stringify({
          result: { status: "ready", message: "ok", count: 1 },
          items: [{ id: "incident-1", display_name: "Suspicious sign-in", severity: "high", status: "active", assigned_to: "analyst@example.test", created_date_time: "2026-08-25T16:00:00Z" }],
          next_cursor: ""
        }), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/diagnostics/access") {
        if (failDiagnostic) {
          return Promise.resolve(new Response(JSON.stringify({ detail: "Diagnostic unavailable" }), { status: 500 }));
        }
        return Promise.resolve(new Response(JSON.stringify(diagnostic), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/runbooks/drafts") {
        return Promise.resolve(new Response(JSON.stringify({
          approval: { id: 42, action_type: "microsoft_admin.powershell_runbook", status: "pending" },
          plan: { plan_digest: "sha256:plan", runbook_id: "windows.service_restart" }
        }), { status: 200 }));
      }
      if (path === "/packs/microsoft-admin/runbooks/plan") {
        return Promise.resolve(new Response(JSON.stringify({
          format: "wait.microsoft-admin.runbook-plan.v1",
          runbook_id: "windows.service_restart",
          runbook_version: "1.0.0",
          title: "Restart an allowlisted Windows service",
          client_id: "acme",
          effect: "write",
          risk_level: 3,
          approval_required: true,
          parameters: { service_name: "BITS", wait_seconds: 7 },
          script_sha256: "sha256:restart",
          timeout_seconds: 45,
          credentials_included: false,
          plan_digest: "sha256:plan"
        }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
    }));
  });

  it("renders tenant posture, recommendations, source readiness, and fixed runbooks", async () => {
    render(<MemoryRouter><MicrosoftAdmin /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Microsoft Administrator" })).toBeInTheDocument();
    expect(await screen.findByText("62.5%")).toBeInTheDocument();
    expect(screen.getByText("Investigate noncompliant Intune devices before relaxing Conditional Access.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Governed PowerShell runbooks" })).toBeInTheDocument();
    expect(screen.getByText("PowerShell runbook execution prerequisites are ready.")).toBeInTheDocument();
    expect(screen.getByLabelText("Runbook")).toHaveValue("windows.endpoint_health");
    expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Source readiness"));
    expect(screen.getByText("Service Health")).toBeInTheDocument();
    expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
  });

  it("runs an access diagnostic and presents the probable cause and governed action", async () => {
    render(<MemoryRouter><MicrosoftAdmin /></MemoryRouter>);
    await screen.findByText("62.5%");

    fireEvent.change(screen.getByLabelText("User principal name or immutable user ID"), {
      target: { value: "adele@example.test" }
    });
    fireEvent.change(screen.getByLabelText("Optional Intune device name"), {
      target: { value: "LAPTOP-001" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Run diagnostic" }));

    const diagnosticStatus = (await screen.findAllByRole("status")).find((node) => node.textContent?.includes("Evidence completeness: 86%"));
    expect(diagnosticStatus).toBeDefined();
    expect(screen.getAllByText("Managed device LAPTOP-001 is not compliant.").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/m365-managed-device-sync/).length).toBeGreaterThan(0);
    const diagnosticCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/packs/microsoft-admin/diagnostics/access");
    expect(diagnosticCall?.[1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(diagnosticCall?.[1]?.body))).toEqual({
      user_identity: "adele@example.test",
      device_name: "LAPTOP-001"
    });
  });

  it("opens risky-user and Defender incident drill-downs from summary cards", async () => {
    render(<MemoryRouter><MicrosoftAdmin /></MemoryRouter>);
    await screen.findByText("62.5%");

    fireEvent.click(screen.getByRole("button", { name: /Risky users/ }));
    expect(await screen.findByRole("heading", { name: "Risky users" })).toBeInTheDocument();
    expect(await screen.findByText("Adele Vance")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show details for Adele Vance" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Defender incidents/ }));
    expect(await screen.findByRole("heading", { name: "Defender incidents" })).toBeInTheDocument();
    expect(await screen.findByText("Suspicious sign-in")).toBeInTheDocument();
  });

  it("creates a tenant-scoped runbook approval draft without executing PowerShell", async () => {
    render(<MemoryRouter><MicrosoftAdmin /></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText("User principal name or immutable user ID"), { target: { value: "adele@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Run diagnostic" }));
    expect(await screen.findByText(/Evidence completeness: 86%/)).toBeInTheDocument();
    const runbookSelect = await screen.findByLabelText("Runbook");
    fireEvent.change(runbookSelect, { target: { value: "windows.service_restart" } });

    const serviceSelect = await screen.findByLabelText("The fixed Windows service to restart.");
    fireEvent.change(serviceSelect, { target: { value: "BITS" } });
    fireEvent.change(screen.getByLabelText("Maximum wait for Running."), {
      target: { value: "7", valueAsNumber: 7 }
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview runbook plan" }));

    expect(await screen.findByRole("heading", { name: "Runbook dry-run preview" })).toBeInTheDocument();
    const planCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/packs/microsoft-admin/runbooks/plan");
    expect(JSON.parse(String(planCall?.[1]?.body))).toEqual({
      runbook_id: "windows.service_restart",
      parameters: { service_name: "BITS", wait_seconds: 7 },
      client_id: "acme"
    });

    fireEvent.click(screen.getByRole("button", { name: "Confirm and create approval draft" }));

    const success = await screen.findByText(/Draft created as approval #42\./);
    expect(success).toHaveTextContent("Draft created as approval #42. No PowerShell has executed.");
    expect(within(success).getByRole("link", { name: "Go to Approvals" })).toHaveAttribute("href", "/approvals");
    const draftCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/packs/microsoft-admin/runbooks/drafts");
    expect(JSON.parse(String(draftCall?.[1]?.body))).toEqual({
      runbook_id: "windows.service_restart",
      parameters: { service_name: "BITS", wait_seconds: 7 },
      client_id: "acme"
    });
  });

  it("blocks drafts without a selected client and hides the form from viewers", async () => {
    dashboardContext.selectedClientId = "";
    const { unmount } = render(<MemoryRouter><MicrosoftAdmin /></MemoryRouter>);
    const draftButton = await screen.findByRole("button", { name: "Preview runbook plan" });
    expect(draftButton).toBeDisabled();
    expect(screen.getByText("Select a client from the top bar before creating a runbook draft.")).toBeInTheDocument();
    unmount();

    dashboardContext.role = "viewer";
    dashboardContext.selectedClientId = "acme";
    render(<MemoryRouter><MicrosoftAdmin /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Technician access required" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create approval draft" })).not.toBeInTheDocument();
  });

  it("preserves available sections when one workspace source or the diagnostic fails", async () => {
    failDashboard = true;
    render(<MemoryRouter><MicrosoftAdmin /></MemoryRouter>);

    expect(await screen.findByText(/We couldn't connect to the appliance/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Governed PowerShell runbooks" })).toBeInTheDocument();

    failDiagnostic = true;
    fireEvent.change(screen.getByLabelText("User principal name or immutable user ID"), {
      target: { value: "adele@example.test" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Run diagnostic" }));
    await waitFor(async () => {
      const diagnosticAlerts = await screen.findAllByRole("alert");
      expect(diagnosticAlerts.some((node) => node.textContent?.includes("The appliance couldn't complete the request"))).toBe(true);
    });
  });
});
