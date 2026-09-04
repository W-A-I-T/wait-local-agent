import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Schedules } from "../src/screens/Schedules";
import { Sidebar } from "../src/app/Sidebar";

const dashboard = vi.hoisted(() => ({
  role: "viewer" as "admin" | "viewer",
  roleResolved: true
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

const jobs = [
  {
    id: 101,
    job_kind: "workflow",
    template_id: "workflow-daily-review",
    playbook_id: null,
    agent_id: null,
    entity_id: null,
    cron: "0 9 * * 1-5",
    schedule_type: "cron",
    interval_seconds: null,
    run_at: null,
    timezone: "UTC",
    paused: false,
    created_at: "2026-08-15T08:00:00Z",
    updated_at: "2026-08-15T08:00:00Z",
    client_id: "acme",
    next_run_at: "2026-08-17T09:00:00Z",
    params: { ticket_id: "HALO-1" }
  },
  {
    id: 102,
    job_kind: "playbook",
    template_id: "playbook-security-review",
    playbook_id: "playbook-security-review",
    agent_id: null,
    entity_id: null,
    cron: "",
    schedule_type: "interval",
    interval_seconds: 3600,
    run_at: null,
    timezone: "America/Vancouver",
    paused: true,
    created_at: "2026-08-15T08:00:00Z",
    updated_at: "2026-08-15T08:00:00Z",
    client_id: "acme",
    next_run_at: "2026-08-16T10:00:00Z",
    params: { input: { priority: "high" } }
  }
];

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Schedules screen", () => {
  it("loads workflow and playbook rows, filters by status, shows next runs, and expands the full view", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe("/scheduled-jobs");
      expect(init?.method ?? "GET").toBe("GET");
      return jsonResponse(jobs);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <Schedules />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Scheduled jobs" })).toBeInTheDocument();
    expect(screen.getByText("Workflow", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Playbook", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("workflow-daily-review")).toBeInTheDocument();
    expect(screen.getByText("playbook-security-review")).toBeInTheDocument();
    expect(screen.getByText("2026-08-17T09:00:00Z")).toBeInTheDocument();
    expect(screen.getByText("Every 1 hour")).toBeInTheDocument();
    expect(screen.getByText("Active", { selector: ".status-chip" })).toBeInTheDocument();
    expect(screen.getByText("Paused", { selector: ".status-chip" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Activity" })).toHaveAttribute("href", "/activity/runs");

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "paused" } });
    expect(screen.queryByText("workflow-daily-review")).not.toBeInTheDocument();
    expect(screen.getByText("playbook-security-review")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show details for scheduled job 102" }));
    expect(await screen.findByRole("heading", { name: "Job 102" })).toBeInTheDocument();
    expect(screen.getByText("America/Vancouver")).toBeInTheDocument();
    expect(screen.getByText(/"priority": "high"/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it("shows the read-only error state", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: "schedules unavailable" }), { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Schedules />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Loading Schedules…")).not.toBeInTheDocument());
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" }
  });
}
