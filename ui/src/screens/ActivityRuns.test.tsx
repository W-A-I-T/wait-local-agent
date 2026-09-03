import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { ActivityRuns } from "./ActivityRuns";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => ({ selectedClientId: "", clients: [] })
}));

const mockedApiFetch = vi.mocked(apiFetch);

const rows = [
  {
    activity_id: "execution:1",
    kind: "agent",
    source_run_id: 10,
    canonical_execution_id: 1,
    title: "Agent 10",
    entity_id: "HALO-10",
    actor: "tech-a",
    status: "completed",
    started_at: "2026-08-31T01:00:00Z",
    finished_at: "2026-08-31T01:01:00Z",
    client_id: "alpha",
    detail_path: "/executions",
    trigger_source: "manual"
  },
  {
    activity_id: "backfill:4",
    kind: "backfill",
    source_run_id: 4,
    canonical_execution_id: null,
    title: "triage-agent",
    entity_id: "",
    actor: "tech-b",
    status: "failed",
    started_at: "2026-08-31T00:00:00Z",
    finished_at: "2026-08-31T00:05:00Z",
    client_id: "alpha",
    detail_path: "/backfills",
    trigger_source: ""
  }
];

describe("ActivityRuns", () => {
  beforeEach(() => mockedApiFetch.mockReset());

  it("renders a unified run stream and retains canonical execution links", async () => {
    mockedApiFetch.mockResolvedValue(rows);

    render(<MemoryRouter><ActivityRuns /></MemoryRouter>);

    expect(await screen.findByText("Agent 10")).toBeInTheDocument();
    expect(screen.getByText("triage-agent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Execution #1" })).toHaveAttribute("href", "/executions");
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", "/backfills");
  });

  it("pushes run kind filtering into the unified API", async () => {
    mockedApiFetch.mockResolvedValue(rows);
    render(<MemoryRouter><ActivityRuns /></MemoryRouter>);
    await screen.findByText("Agent 10");

    fireEvent.click(screen.getByRole("button", { name: "Backfill" }));

    await waitFor(() => expect(mockedApiFetch).toHaveBeenLastCalledWith(
      expect.stringContaining("kinds=backfill")
    ));
  });

  it("shows an empty state when filters match no activity", async () => {
    mockedApiFetch.mockResolvedValue([]);
    render(<MemoryRouter><ActivityRuns /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "No matching runs" })).toBeInTheDocument();
  });

  it("surfaces invalid activity data without a fake run list", async () => {
    mockedApiFetch.mockResolvedValue({});
    render(<MemoryRouter><ActivityRuns /></MemoryRouter>);

    expect(await screen.findByRole("alert")).toHaveTextContent("invalid activity data");
    expect(screen.getByRole("heading", { name: "No matching runs" })).toBeInTheDocument();
  });
});
