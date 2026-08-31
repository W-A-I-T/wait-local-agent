import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Events } from "../src/screens/Events";
import { Sidebar } from "../src/app/Sidebar";

const dashboard = vi.hoisted(() => ({
  role: "viewer" as "admin" | "viewer",
  roleResolved: true
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

const deliveries = [
  {
    id: 7,
    idempotency_key: "evt-7",
    event_type: "ticket.updated",
    entity_type: "ticket",
    entity_id: "HALO-1",
    payload: { status: "Open" },
    status: "failed",
    error_detail: "Agent triage was blocked",
    matched_agent_count: 1,
    retry_count: 1,
    max_retries: 3,
    retry_delay_seconds: 60,
    next_retry_at: "2026-08-15T10:02:00Z",
    received_at: "2026-08-15T10:00:00Z",
    processed_at: "2026-08-15T10:01:00Z",
    client_id: "acme"
  },
  {
    id: 8,
    idempotency_key: "evt-8",
    event_type: "ticket.created",
    entity_type: "ticket",
    entity_id: "HALO-2",
    status: "delivered",
    retry_count: 0,
    max_retries: 3,
    retry_delay_seconds: 60,
    received_at: "2026-08-15T09:00:00Z",
    processed_at: "2026-08-15T09:00:01Z",
    client_id: "acme"
  },
  {
    id: 9,
    idempotency_key: "evt-9",
    event_type: "ticket.pending",
    entity_type: "ticket",
    entity_id: "HALO-3",
    status: "pending",
    retry_count: 0,
    max_retries: 3,
    retry_delay_seconds: 60,
    received_at: "2026-08-15T08:00:00Z",
    processed_at: "",
    client_id: "acme"
  }
];

const history = [{
  id: 1,
  event_type: "halopsa.write",
  subject_id: "HALO-1",
  status: "succeeded",
  message: "Ticket update recorded",
  payload_json: "{}",
  created_at: "2026-08-15T10:01:00Z",
  client_id: "acme"
}];

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Events screen", () => {
  it("loads deliveries and history, renders status badges, opens detail, and exposes viewer navigation", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/automation/event-deliveries") return jsonResponse(deliveries);
      if (path === "/automation/event-deliveries/7") return jsonResponse(deliveries[0]);
      if (path === "/event-history") return jsonResponse(history);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <Events />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Deliveries" })).toBeInTheDocument();
    expect(screen.getByText("ticket.updated")).toBeInTheDocument();
    expect(screen.getByText("ticket.created")).toBeInTheDocument();
    expect(screen.getByText("ticket.pending")).toBeInTheDocument();
    expect(screen.getByText("Failed — needs attention")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("halopsa.write")).toBeInTheDocument();
    expect(screen.getByText("Ticket update recorded")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Activity" })).toHaveAttribute("href", "/activity/runs");

    fireEvent.click(screen.getByRole("button", { name: "Open delivery 7: ticket.updated" }));
    expect(await screen.findByRole("heading", { name: "Delivery 7" })).toBeInTheDocument();
    expect(screen.getByText("Agent triage was blocked")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Payload" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/automation/event-deliveries/7", expect.anything());
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain("/automation/event-deliveries/7/retry");
  });

  it("shows the read-only error state", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/automation/event-deliveries") {
        return new Response(JSON.stringify({ detail: "deliveries unavailable" }), { status: 503 });
      }
      return jsonResponse(history);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Events />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Loading Events…")).not.toBeInTheDocument());
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" }
  });
}
