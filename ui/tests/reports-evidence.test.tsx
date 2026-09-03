import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Reports } from "../src/screens/Reports";

const dashboard = vi.hoisted(() => ({
  role: "admin" as "admin" | "viewer",
  roleResolved: true,
  clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
  selectedClientId: "acme",
  isMspAdmin: false
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({
    role: dashboard.role,
    roleResolved: dashboard.roleResolved,
    clients: dashboard.clients,
    selectedClientId: dashboard.selectedClientId,
    isMspAdmin: dashboard.isMspAdmin
  })
}));

const stateCopy = {
  not_run: ["These checks haven't been run yet", "A restore drill hasn't been run yet"],
  no_evidence: ["A run was recorded but produced no evidence", "A drill was recorded but produced no evidence"],
  partial: ["Some checks couldn't complete", "Some parts of the restore drill couldn't complete"],
  completed: ["Checks completed", "Restore drill completed"]
} as const;

describe("Reports evidence views", () => {
  beforeEach(() => {
    dashboard.role = "admin";
    dashboard.roleResolved = true;
    vi.stubGlobal("fetch", vi.fn(baseFetch));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each(Object.entries(stateCopy))("renders the %s evidence state in plain language", async (status, copy) => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => evidenceFetch(String(input), status)));

    render(<Reports />);

    expect((await screen.findAllByText(copy[0])).length).toBeGreaterThan(0);
    expect(screen.getByText(copy[1])).toBeInTheDocument();
    if (status === "not_run") {
      expect(screen.queryByText("Checks completed")).not.toBeInTheDocument();
    }
  });

  it("shows failed-check remediation and restore verification evidence", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/reports") {
        return json([report("appliance_hardening", "partial"), report("restore_evidence", "completed")]);
      }
      if (path === "/hardening/runs") {
        return json([{
          id: 7,
          status: "partial",
          started_at: "2026-08-07T10:00:00Z",
          completed_at: "2026-08-07T10:01:00Z",
          expected_check_count: 2,
          result_count: 2,
          results: [{
            id: 3,
            run_id: 7,
            check_id: "backup-recency",
            title: "Backup recency",
            scope: "storage",
            severity: "high",
            status: "failed",
            evidence: { backups: [] },
            remediation_hint: "Create a backup newer than the configured recency window."
          }]
        }]);
      }
      if (path === "/backup/restore-exercises") {
        return json([{
          id: 8,
          exercise_id: "restore-8",
          status: "passed",
          target: "temporary scratch database",
          backup_artifact_id: "/safe/backup.db",
          validation_json: JSON.stringify({ verified_tables: ["tickets", "approvals"], duration_seconds: 1.25 }),
          evidence_json: "{}",
          started_at: "2026-08-07T10:00:00Z",
          completed_at: "2026-08-07T10:00:02Z"
        }]);
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<Reports />);

    expect(await screen.findByText("Recommended fix: Create a backup newer than the configured recency window.")).toBeInTheDocument();
    expect(screen.getByText("Priority: High")).toBeInTheDocument();
    expect(screen.getByText("Coverage: Stored appliance data")).toBeInTheDocument();
    expect(screen.getByText("Verified 2 stored record groups")).toBeInTheDocument();
    expect(screen.getByText("Duration: 1.3 seconds")).toBeInTheDocument();
  });

  it("keeps run controls read-only for non-admin roles", async () => {
    dashboard.role = "viewer";

    render(<Reports />);

    expect(await screen.findByText("You have read-only access. An administrator can run these checks.")).toBeInTheDocument();
    expect(screen.getByText("You have read-only access. An administrator can run a restore drill.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run checks now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run a restore drill" })).not.toBeInTheDocument();
  });

  it("never presents a slow evidence fetch as not run", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

    render(<Reports />);

    expect(screen.getByText("Loading hardening evidence")).toBeInTheDocument();
    expect(screen.getByText("Loading restore drill evidence")).toBeInTheDocument();
    expect(screen.queryByText("These checks haven't been run yet")).not.toBeInTheDocument();
    expect(screen.queryByText("A restore drill hasn't been run yet")).not.toBeInTheDocument();
    expect(screen.queryByText("Not run yet")).not.toBeInTheDocument();
  });

  it("shows a plain-language transport error and keeps its raw detail technical", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Response(JSON.stringify({ detail: "backend rejection" }), { status: 403 })));

    render(<Reports />);

    expect(await screen.findByRole("status")).toHaveTextContent("You do not have permission to do that. Check your access and try again.");
    const technicalDetail = screen.getByText(/\/reports failed with HTTP 403/);
    expect(technicalDetail.closest("details")).toBeInTheDocument();
  });

  it("exposes downloadable JSON and Markdown exports for both evidence reports", async () => {
    const createObjectUrl = vi.fn(() => "blob:report");
    const revokeObjectUrl = vi.fn();
    Object.assign(URL, { createObjectURL: createObjectUrl, revokeObjectURL: revokeObjectUrl });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<Reports />);

    const hardeningExports = await screen.findByLabelText("Hardening posture exports");
    const restoreExports = screen.getByLabelText("Restore drill evidence exports");
    expect(within(hardeningExports).getByRole("button", { name: "Export JSON" })).toBeEnabled();
    expect(within(restoreExports).getByRole("button", { name: "Export Markdown" })).toBeEnabled();

    fireEvent.click(within(hardeningExports).getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/reports/appliance_hardening-report/export?export_format=json",
      expect.anything()
    ));
    fireEvent.click(within(restoreExports).getByRole("button", { name: "Export Markdown" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/reports/restore_evidence-report/export?export_format=markdown",
      expect.anything()
    ));
  });

  it("generates a client QBR through the bounded report API", async () => {
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push([input, init]);
      if (String(input) === "/reports/qbr" && init?.method === "POST") {
        return json({
          id: "qbr-1",
          report_type: "qbr",
          client_id: "acme",
          project_id: "",
          created_at: "2026-08-09T10:00:00Z",
          title: "Quarterly business review — acme",
          evidence_status: "partial",
          metadata: { evidence_status: "partial" },
          sections: []
        });
      }
      return evidenceFetch(String(input), "completed");
    }));

    render(<Reports />);
    await screen.findByText("Client reports");
    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2026-08-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate QBR" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Qbr report generated from local evidence.");
    expect(calls.some(([input, init]) => (
      String(input) === "/reports/qbr"
      && init?.method === "POST"
      && String(init.body).includes('"client_id":"acme"')
      && String(init.body).includes('"period_start":"2026-08-01"')
    ))).toBe(true);
  });

  it("generates a recurring service review through the bounded report API", async () => {
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push([input, init]);
      if (String(input) === "/reports/recurring-service-review" && init?.method === "POST") {
        return json({
          id: "review-1",
          report_type: "recurring_service_review",
          client_id: "acme",
          project_id: "",
          created_at: "2026-08-09T10:00:00Z",
          title: "Recurring service review — acme",
          evidence_status: "partial",
          metadata: { evidence_status: "partial", follow_up_after_days: 14 },
          sections: []
        });
      }
      return evidenceFetch(String(input), "completed");
    }));

    render(<Reports />);
    await screen.findByText("Client reports");
    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2026-08-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate service review" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Recurring service review report generated from local evidence.");
    expect(calls.some(([input, init]) => (
      String(input) === "/reports/recurring-service-review"
      && init?.method === "POST"
      && String(init.body).includes('"client_id":"acme"')
    ))).toBe(true);
  });
});

function baseFetch(input: RequestInfo | URL): Response {
  return evidenceFetch(String(input), "completed");
}

function evidenceFetch(path: string, status: string): Response {
  if (path === "/reports") {
    return json([report("appliance_hardening", status), report("restore_evidence", status)]);
  }
  if (path === "/hardening/runs" || path === "/backup/restore-exercises") {
    return json([]);
  }
  if (path.includes("/export?")) {
    return new Response("exported", { status: 200, headers: { "Content-Type": "text/plain" } });
  }
  throw new Error(`Unexpected request: ${path}`);
}

function report(reportType: "appliance_hardening" | "restore_evidence", evidenceStatus: string) {
  return {
    id: `${reportType}-report`,
    report_type: reportType,
    project_id: null,
    created_at: "2026-08-07T10:00:00Z",
    updated_at: "2026-08-07T10:00:00Z",
    status: "completed",
    subject: reportType,
    title: reportType,
    evidence_status: evidenceStatus,
    metadata: { evidence_status: evidenceStatus },
    sections: []
  };
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
