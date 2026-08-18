import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { SmartActionRuns } from "./SmartActionRuns";

vi.mock("../api/client", () => ({ apiFetch: vi.fn(), ApiRequestError: class ApiRequestError extends Error { status?: number; constructor(message: string, _technicalDetail?: string, status?: number) { super(message); this.status = status; } } }));
vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedUseDashboard = vi.mocked(useDashboard);

const run = {
  id: 7,
  action_id: "m365.device_reboot",
  actor: "operator@example.com",
  status: "completed",
  payload_digest: "sha256:abc",
  output: { device_id: "device-1", result: "queued" },
  evidence: [{ source: "m365", status: "accepted" }],
  approval_id: 12,
  created_at: "2026-08-17T00:00:00Z",
  updated_at: "2026-08-17T00:01:00Z",
  client_id: "acme",
  error_detail: ""
};

describe("SmartActionRuns", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedUseDashboard.mockReturnValue({ selectedClientId: "acme" } as never);
  });

  it("loads the client-scoped run list and detail output", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/smart-actions/runs?client_id=acme") return Promise.resolve([run]) as ReturnType<typeof apiFetch>;
      if (path === "/smart-actions/runs/7?client_id=acme") return Promise.resolve(run) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<SmartActionRuns />);
    expect(await screen.findByText("m365.device_reboot")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "m365.device_reboot" }));

    expect(await screen.findByText(/device-1/)).toBeInTheDocument();
    expect(screen.getByText(/accepted/)).toBeInTheDocument();
    expect(screen.getByText("Approval 12")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/smart-actions/runs/7?client_id=acme");
    expect(screen.queryByRole("button", { name: /invoke|execute|retry|post/i })).not.toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    mockedApiFetch.mockResolvedValue([]);
    render(<SmartActionRuns />);
    expect(await screen.findByText("No smart action runs yet.")).toBeInTheDocument();
  });

  it("shows detail errors and handles a missing run gracefully", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/smart-actions/runs?client_id=acme") return Promise.resolve([run]) as ReturnType<typeof apiFetch>;
      return Promise.reject(new ApiRequestError("Not found", "Not found", 404)) as ReturnType<typeof apiFetch>;
    });

    render(<SmartActionRuns />);
    fireEvent.click(await screen.findByRole("button", { name: "m365.device_reboot" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("not found in the current client scope"));
  });
});
