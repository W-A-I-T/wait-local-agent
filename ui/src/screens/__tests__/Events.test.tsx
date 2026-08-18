import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api/client";
import { useDashboard } from "../../app/DashboardContext";
import type { EventDelivery, EventHistory } from "../../api/types";
import { Events } from "../Events";

vi.mock("../../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedUseDashboard = vi.mocked(useDashboard);

function delivery(overrides: Partial<EventDelivery> = {}): EventDelivery {
  return {
    id: 42,
    idempotency_key: "event-42",
    event_type: "ticket.updated",
    entity_type: "ticket",
    entity_id: "TCK-42",
    status: "failed",
    retry_count: 1,
    max_retries: 3,
    retry_delay_seconds: 10,
    received_at: "2026-08-17T00:00:00Z",
    processed_at: "2026-08-17T00:00:01Z",
    ...overrides
  };
}

function configure(deliveries: EventDelivery[]) {
  mockedApiFetch.mockImplementation((path) => {
    if (path === "/automation/event-deliveries") return Promise.resolve(deliveries) as ReturnType<typeof apiFetch>;
    if (path === "/event-history") return Promise.resolve([] as EventHistory[]) as ReturnType<typeof apiFetch>;
    throw new Error(`Unexpected request: ${path}`);
  });
}

describe("Events delivery retry", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedUseDashboard.mockReturnValue({ retryEventDelivery: vi.fn().mockResolvedValue(undefined) } as never);
  });

  it("shows and invokes retry for a failed delivery below its retry limit", async () => {
    const retryEventDelivery = vi.fn().mockResolvedValue(undefined);
    mockedUseDashboard.mockReturnValue({ retryEventDelivery } as never);
    configure([delivery()]);

    render(<Events />);
    const button = await screen.findByRole("button", { name: "Retry delivery" });
    fireEvent.click(button);

    await waitFor(() => expect(retryEventDelivery).toHaveBeenCalledWith(42));
    expect(mockedApiFetch).toHaveBeenCalledTimes(4);
  });

  it("does not show retry for non-retryable deliveries", async () => {
    configure([delivery({ id: 43, retry_count: 3 }), delivery({ id: 44, status: "delivered" })]);

    render(<Events />);
    await screen.findByText("Delivery 43");
    expect(screen.queryByRole("button", { name: "Retry delivery" })).not.toBeInTheDocument();
  });
});
