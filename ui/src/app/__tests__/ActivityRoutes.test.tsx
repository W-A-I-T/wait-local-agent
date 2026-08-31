import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../../routes";

vi.mock("../../screens/Events", () => ({ Events: () => <div>Events screen</div> }));
vi.mock("../../screens/Schedules", () => ({ Schedules: () => <div>Schedules screen</div> }));
vi.mock("../../screens/ScheduledJobs", () => ({ ScheduledJobs: () => <div>Scheduled Jobs screen</div> }));
vi.mock("../../screens/SmartActionRuns", () => ({ SmartActionRuns: () => <div>Smart Action Runs screen</div> }));
vi.mock("../../screens/Executions", () => ({ Executions: () => <div>Executions screen</div> }));
vi.mock("../../screens/Backfills", () => ({ Backfills: () => <div>Backfills screen</div> }));

const activityRoutes = [
  ["/automation/events", "Events"],
  ["/automation/schedules", "Schedules"],
  ["/scheduled-jobs", "Scheduled Jobs"],
  ["/smart-actions/runs", "Smart Action Runs"],
  ["/executions", "Executions"],
  ["/backfills", "Backfills"]
] as const;

describe("activity routes", () => {
  it.each(activityRoutes)("renders the %s screen inside ActivityShell", (path, label) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: "Activity & scheduling" })).toBeInTheDocument();
    expect(screen.getByText(`${label} screen`)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  });
});
