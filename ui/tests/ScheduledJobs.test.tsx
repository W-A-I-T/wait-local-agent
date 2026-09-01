import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScheduledJobs } from "../src/screens/ScheduledJobs";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, clients: [{ client_id: "acme", name: "Acme Support", status: "active" }], selectedClientId: "acme", setSelectedClientId: vi.fn() })
}));

const jobs = vi.fn();

describe("ScheduledJobs", () => {
  beforeEach(() => {
    jobs.mockReset();
    jobs.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/scheduled-jobs") && (!init || init.method === "GET")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path.endsWith("/workflows/templates")) {
        return Promise.resolve(new Response(JSON.stringify([{ id: "ticket-triage", name: "Ticket triage" }]), { status: 200 }));
      }
      if (path.endsWith("/agents")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (path.endsWith("/msp/playbooks")) {
        return Promise.resolve(new Response(JSON.stringify([{ id: "ticket-intake-review", name: "Ticket intake review" }]), { status: 200 }));
      }
      if (path.endsWith("/scheduled-jobs") && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({
          id: 1,
          job_kind: "report",
          template_id: "qbr",
          agent_id: null,
          entity_id: null,
          cron: "0 */6 * * *",
          schedule_type: "cron",
          timezone: "UTC",
          paused: false,
          created_at: "2026-08-09T00:00:00Z",
          updated_at: "2026-08-09T00:00:00Z",
          client_id: "acme",
          next_run_at: null,
          params: { client_id: "acme", period_days: 90 }
        }), { status: 200 }));
      }
      return new Response(JSON.stringify([]), { status: 200 });
    });
    vi.stubGlobal("fetch", jobs);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a client report schedule through the existing API", async () => {
    render(<ScheduledJobs />);

    await screen.findByText("Scheduled Jobs");
    fireEvent.change(screen.getByLabelText("Schedule type"), { target: { value: "report" } });
    fireEvent.change(screen.getByLabelText("Params JSON"), { target: { value: '{"period_days":90}' } });
    fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() => expect(jobs).toHaveBeenCalledWith(
      "/scheduled-jobs",
      expect.objectContaining({ method: "POST" })
    ));
    const request = jobs.mock.calls.find(([, init]) => init?.method === "POST")?.[1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      report_type: "qbr",
      cron: "0 */6 * * *",
      timezone: "UTC",
      params: { client_id: "acme", period_days: 90 }
    });
    expect(await screen.findByText("Scheduled job created.")).toBeInTheDocument();
  });

  it("offers the backend-supported recurring service review report target", async () => {
    render(<ScheduledJobs />);

    await screen.findByText("Scheduled Jobs");
    fireEvent.change(screen.getByLabelText("Schedule type"), { target: { value: "report" } });
    fireEvent.change(screen.getByLabelText("Report"), { target: { value: "recurring_service_review" } });
    fireEvent.change(screen.getByLabelText("Params JSON"), { target: { value: '{"period_days":30,"follow_up_after_days":14}' } });
    fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() => expect(jobs).toHaveBeenCalledWith(
      "/scheduled-jobs",
      expect.objectContaining({ method: "POST" })
    ));
    const request = jobs.mock.calls.find(([, init]) => init?.method === "POST")?.[1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      report_type: "recurring_service_review",
      cron: "0 */6 * * *",
      timezone: "UTC",
      params: { client_id: "acme", period_days: 30, follow_up_after_days: 14 }
    });
  });

  it("creates a playbook schedule with the backend-supported target and params", async () => {
    render(<ScheduledJobs />);

    await screen.findByText("Scheduled Jobs");
    fireEvent.change(screen.getByLabelText("Schedule type"), { target: { value: "playbook" } });
    fireEvent.change(screen.getByLabelText("Playbook"), { target: { value: "ticket-intake-review" } });
    fireEvent.change(screen.getByLabelText("Params JSON"), { target: { value: '{"ticket_id":"T-1","input":{"priority":"high"}}' } });
    fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() => expect(jobs).toHaveBeenCalledWith(
      "/scheduled-jobs",
      expect.objectContaining({ method: "POST" })
    ));
    const request = jobs.mock.calls.find(([, init]) => init?.method === "POST")?.[1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      playbook_id: "ticket-intake-review",
      cron: "0 */6 * * *",
      timezone: "UTC",
      params: { client_id: "acme", ticket_id: "T-1", input: { priority: "high" } }
    });
  });
});
