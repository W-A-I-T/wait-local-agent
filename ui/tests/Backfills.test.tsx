import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Backfills } from "../src/screens/Backfills";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({
    canWrite: true,
    selectedClientId: "acme",
    clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
    isMspAdmin: false
  })
}));

describe("Backfills", () => {
  const agent = {
    id: "agent-1",
    name: "Ticket triage",
    description: "Bounded triage.",
    enabled: true,
    trigger: "manual",
    entity_type: "ticket",
    filters: {},
    enabled_tools: ["ticket-triage"],
    steps: [{ tool_id: "ticket-triage", payload: {} }],
    max_steps: 1,
    execution_timeout_seconds: 30,
    client_id: "acme",
    version: 1,
    run_once_per_entity: true,
    depends_on_agent_ids: [],
    context_sources: ["ticket"],
    approval_expiry_seconds: null
  };
  const backfill = {
    id: 3,
    agent_id: "agent-1",
    entity_ids: ["TCK-1001", "TCK-1002"],
    input: {},
    max_concurrency: 1,
    status: "completed_with_errors",
    next_index: 2,
    processed_count: 2,
    succeeded_count: 1,
    failed_count: 1,
    run_ids: [9],
    failed_entity_ids: ["TCK-1002"],
    actor: "operator",
    error_detail: "TCK-1002: unavailable",
    created_at: "2026-08-08T00:00:00Z",
    updated_at: "2026-08-08T00:01:00Z",
    client_id: "acme"
  };

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/agents" && !init?.method) return Promise.resolve(new Response(JSON.stringify([agent]), { status: 200 }));
      if (path === "/agent-backfills" && !init?.method) return Promise.resolve(new Response(JSON.stringify([backfill]), { status: 200 }));
      if (path === "/agent-backfills/preview") return Promise.resolve(new Response(JSON.stringify({
        dry_run: true,
        agent_id: "agent-1",
        entity_count: 2,
        estimated_runs: 2,
        max_concurrency: 1,
        execution_mode: "sequential",
        will_persist: false,
        input: {},
        client_id: "acme"
      }), { status: 200 }));
      if (path === "/agent-backfills" && init?.method === "POST") return Promise.resolve(new Response(JSON.stringify({ ...backfill, status: "queued" }), { status: 200 }));
      if (path === "/agent-backfills/3/rerun-failed") return Promise.resolve(new Response(JSON.stringify({ ...backfill, failed_entity_ids: [], status: "completed" }), { status: 200 }));
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("previews and queues a bounded backfill, showing failed items", async () => {
    render(<MemoryRouter><Backfills /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Agent Backfills" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ticket IDs"), { target: { value: "TCK-1001\nTCK-1002" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Preview: 2 entities, sequential, no data persisted.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Queue backfill" }));
    await waitFor(() => expect(screen.getByText("Backfill queued.")).toBeInTheDocument());
    expect(screen.getByText("Failed: TCK-1002")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rerun failed" }));
    await waitFor(() => expect(screen.getByText("Backfill failed items rerun.")).toBeInTheDocument());
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input]) => String(input) === "/agent-backfills/preview"
    )).toBe(true);
  });
});
