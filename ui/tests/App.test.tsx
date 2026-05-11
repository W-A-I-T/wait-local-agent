import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

const approvals = [
  {
    id: 1,
    subject_id: "HALO-1",
    action_type: "halopsa.add_note",
    status: "pending",
    comment: "",
    execution_status: "not_started",
    execution_message: "",
    payload: { fields: { note: "Call customer", status: "In Progress" } },
    can_execute: false,
    block_reason: "",
    workflow_run_id: "run-1"
  },
  {
    id: 2,
    subject_id: "TCK-1001",
    action_type: "ticket.assign",
    status: "pending",
    comment: "",
    execution_status: "not_started",
    execution_message: "",
    payload: { fields: { technician: "Avery" } },
    can_execute: false,
    block_reason: "",
    workflow_run_id: null
  }
];

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(mockFetch));
  });

  it("renders API-backed HaloPSA live operations dashboard", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "HaloPSA Live Operations" })).toBeInTheDocument();
    expect((await screen.findAllByText("HALO-1")).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Approval Queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Connector Readiness" })).toBeInTheDocument();
    expect(screen.getByText("Hudu connector")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "Payload Preview" }).length).toBeGreaterThan(0);
    expect(screen.getByText(/Workflow run run-1: running/)).toBeInTheDocument();
    expect(screen.getAllByText("ready").length).toBeGreaterThan(0);
  });

  it("creates drafts, edits payload fields, and approves from controls", async () => {
    render(<App />);

    await screen.findAllByText("HALO-1");
    fireEvent.click(screen.getByRole("button", { name: /Create Draft/i }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/connectors/halopsa/tickets/HALO-1/drafts",
        expect.objectContaining({ method: "POST" })
      );
    });

    fireEvent.change(screen.getAllByLabelText("Draft Fields")[0], {
      target: { value: "note=Updated from workbench\nstatus=Waiting" }
    });
    fireEvent.click(screen.getAllByRole("button", { name: /Save Fields/i })[0]);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/approval-requests/1/payload",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ fields: { note: "Updated from workbench", status: "Waiting" } })
        })
      );
    });

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /Approve/i })[0]).toBeEnabled();
    });
    fireEvent.click(screen.getAllByRole("button", { name: /Approve/i })[0]);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/approval-requests/1",
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("keeps approvals available while Halo execution is blocked", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => mockFetch(input, true)));
    render(<App />);

    expect(await screen.findByText("blocked")).toBeInTheDocument();
    await screen.findByText("halopsa.add_note");
    expect(screen.getAllByRole("button", { name: /Approve/i })[0]).toBeEnabled();
    expect(screen.getAllByRole("button", { name: /Approve/i })[1]).toBeEnabled();

    fireEvent.click(screen.getAllByRole("button", { name: /Approve/i })[0]);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/approval-requests/1",
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("renders empty and error states for unavailable API sections", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input) === "/approval-requests") {
        return json([]);
      }
      if (String(input) === "/workflow-runs") {
        return new Response("offline", { status: 503 });
      }
      return mockFetch(input);
    }));

    render(<App />);

    expect(await screen.findByText("No approval requests yet.")).toBeInTheDocument();
    expect(screen.getByText("No workflow runs visible.")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("/workflow-runs failed with HTTP 503");
  });
});

async function mockFetch(input: RequestInfo | URL, blocked = false): Promise<Response> {
  const path = String(input);
  if (path === "/connectors") {
    return json([
      {
        id: "halopsa",
        name: "HaloPSA",
        status: blocked ? "blocked" : "ready",
        message: "HaloPSA connector",
        write_actions_enabled: !blocked,
        http_probing_enabled: !blocked
      },
      {
        id: "hudu",
        name: "Hudu",
        status: blocked ? "blocked" : "ready",
        message: "Hudu connector",
        write_actions_enabled: false,
        http_probing_enabled: !blocked
      }
    ]);
  }
  if (path === "/connectors/halopsa/write-health") {
    return json({
      status: blocked ? "blocked" : "ready",
      message: blocked ? "writes blocked" : "writes ready",
      count: 0
    });
  }
  if (path === "/connectors/halopsa/tickets") {
    return json({
      result: { status: "ready", message: "ok", count: 1 },
      items: [{ id: "HALO-1", summary: "Printer offline", status: "Open", priority: "High" }]
    });
  }
  if (path === "/approval-requests") {
    return json(approvals);
  }
  if (path === "/workflow-runs") {
    return json([
      {
        id: "run-1",
        status: "running",
        goal: "Prepare HaloPSA note",
        message: "Waiting for approval",
        approval_request_id: 1
      }
    ]);
  }
  if (path === "/event-history") {
    return json([
      {
        id: 1,
        event_type: "halopsa.write",
        subject_id: "HALO-1",
        status: "succeeded",
        message: "posted"
      }
    ]);
  }
  if (path.includes("/drafts") || path === "/approval-requests/1") {
    return json({ ...approvals[0], status: "approved", execution_status: "succeeded" });
  }
  if (path === "/approval-requests/1/payload") {
    return json(approvals[0]);
  }
  if (path === "/approval-requests/2") {
    return json({ ...approvals[1], status: "approved" });
  }
  return json({});
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
