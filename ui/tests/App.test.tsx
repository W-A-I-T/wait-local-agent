import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

// These tests cover the original all-sections dashboard contract. Keep that
// contract in the test while the production shell exposes the sections as
// separate routes.
vi.mock("../src/routes", async () => {
  const [{ Approvals }, { Connectors }, { Overview }, { Tickets }] = await Promise.all([
    import("../src/screens/Approvals"),
    import("../src/screens/Connectors"),
    import("../src/screens/Overview"),
    import("../src/screens/Tickets")
  ]);

  return {
    AppRoutes: () => (
      <>
        <Overview />
        <Connectors />
        <Tickets />
        <Approvals />
      </>
    )
  };
});

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
    expires_at: "2026-08-09T00:00:00+00:00",
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
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn(mockFetch));
  });

  it("renders the API-backed Solutions Architect and MSP dashboard", async () => {
    renderApp();

    expect(await screen.findByRole("heading", { name: "WAIT AI Solutions Architect" })).toBeInTheDocument();
    expect(await screen.findByText("Local mode · full access")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getByLabelText("Signed-in account")).toHaveTextContent("Local appliance");
    fireEvent.click(screen.getByRole("button", { name: "Explain local mode" }));
    expect(screen.getByText(/access controls are off/i)).toBeInTheDocument();
    expect(screen.getByText(/configure an administrator or team access credential/i)).toBeInTheDocument();
    expect(screen.getByText("Local-first solution design, governed execution, and MSP operations.")).toBeInTheDocument();
    expect((await screen.findAllByText("HALO-1")).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Approval Queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Connector Readiness" })).toBeInTheDocument();
    expect(screen.getAllByText("Hudu connector").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("heading", { name: "Payload Preview" }).length).toBeGreaterThan(0);
    expect(screen.getByText(/Workflow run run-1: running/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Automation delivery retries" })).toBeInTheDocument();
    expect(screen.getByText("ticket.updated")).toBeInTheDocument();
    expect(screen.getByText("Approval deadline: 2026-08-09T00:00:00+00:00")).toBeInTheDocument();
  });

  it("retries a failed automation delivery from the overview", async () => {
    renderApp();

    const retryButton = await screen.findByRole("button", { name: "Retry event delivery 7" });
    fireEvent.click(retryButton);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/automation/event-deliveries/7/retry",
      expect.objectContaining({ method: "POST" })
    ));
  });

  it("creates drafts, edits payload fields, and approves from controls", async () => {
    renderApp();

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
    renderApp();

    expect((await screen.findAllByText("blocked")).length).toBeGreaterThan(0);
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
      if (String(input) === "/auth/role") {
        return json({ role: "admin", api_auth_required: false, demo_mode: true });
      }
      if (String(input) === "/approval-requests") {
        return json([]);
      }
      if (String(input) === "/workflow-runs") {
        return new Response("offline", { status: 503 });
      }
      return mockFetch(input);
    }));

    renderApp();

    expect(await screen.findByText("No approval requests yet.")).toBeInTheDocument();
    expect(screen.getByText("No workflow runs visible.")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
  });

  it("does not present onboarding as demo-ready when dashboard access is denied", async () => {
    window.localStorage.setItem("wait-local-agent-api-token", "rejected-token");
    vi.stubGlobal("fetch", vi.fn(() => new Response(JSON.stringify({ detail: "invalid token" }), {
      status: 401,
      headers: { "Content-Type": "application/json" }
    })));

    renderApp();

    expect(await screen.findByRole("heading", { name: "Sign in to the appliance" })).toBeInTheDocument();
    expect(screen.getByLabelText("Access token")).toBeInTheDocument();
    expect(screen.queryByText("rejected-token")).not.toBeInTheDocument();
    expect(screen.queryByText("demo-ready")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Set up your MSP operations" })).not.toBeInTheDocument();
  });

  it("hides write controls for viewer role", async () => {
    window.localStorage.setItem("wait-local-agent-api-token", "viewer-token");
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => mockFetch(input, false, "viewer")));

    renderApp();

    expect(await screen.findByText("Role: viewer")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Draft HaloPSA Write" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Provider And Secrets" })).not.toBeInTheDocument();
  });

  it("sends bearer tokens from stored dashboard auth", async () => {
    window.localStorage.setItem("wait-local-agent-api-token", "viewer-token");

    renderApp();

    await screen.findByRole("heading", { name: "WAIT AI Solutions Architect" });

    const authRoleCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/auth/role");
    expect(authRoleCall).toBeDefined();
    expect(new Headers(authRoleCall?.[1]?.headers).get("Authorization")).toBe("Bearer viewer-token");
  });

  it("reports the resolved role after saving a token", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input) === "/auth/role" && !window.localStorage.getItem("wait-local-agent-api-token")) {
        return new Response(JSON.stringify({ detail: "missing token" }), { status: 401 });
      }
      return mockFetch(input);
    }));
    renderApp();

    const tokenInput = await screen.findByLabelText("Access token");
    fireEvent.change(tokenInput, { target: { value: "new-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Signed in.");
  });
});

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>
  );
}

async function mockFetch(
  input: RequestInfo | URL,
  blocked = false,
  role: "admin" | "technician" | "viewer" = "admin"
): Promise<Response> {
  const path = String(input);
  if (path === "/auth/role") {
    return json({ role, api_auth_required: role !== "admin", demo_mode: false });
  }
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
  if (path === "/automation/event-deliveries") {
    return json([{
      id: 7,
      idempotency_key: "evt-7",
      event_type: "ticket.updated",
      entity_type: "ticket",
      entity_id: "HALO-1",
      status: "failed",
      error_detail: "Agent triage was blocked",
      retry_count: 1,
      max_retries: 3,
      retry_delay_seconds: 60,
      next_retry_at: "2026-08-09T00:01:00+00:00",
      client_id: "acme"
    }]);
  }
  if (path === "/automation/event-deliveries/7/retry") {
    return json({ delivery: { id: 7, status: "completed" } });
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
