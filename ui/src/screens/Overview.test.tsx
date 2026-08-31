import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Overview } from "./Overview";
import { useDashboard } from "../app/DashboardContext";

vi.mock("../app/DashboardContext", () => ({
  useDashboard: vi.fn()
}));
vi.mock("../components/SetupStatus", () => ({
  SetupStatus: () => <div>Setup status</div>
}));
vi.mock("../surfaces/onboarding/OnboardingWizard", () => ({
  OnboardingWizard: () => <div>Onboarding wizard</div>
}));

const mockedUseDashboard = vi.mocked(useDashboard);

describe("Overview automation entry", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedUseDashboard.mockReturnValue({
      connectors: [],
      liveWritesReady: false,
      writeHealth: { status: "blocked", message: "Writes are gated.", count: 0 },
      workflowRuns: [],
      eventHistory: [],
      eventDeliveries: [],
      retryEventDelivery: vi.fn(),
      canWrite: false,
      isConfigured: true,
      configurationLoading: false,
      roleResolved: true
    } as never);
  });

  it("presents verified no-ticket automation destinations", () => {
    render(<MemoryRouter><Overview /></MemoryRouter>);

    expect(screen.getByText("Automate something")).toBeInTheDocument();
    expect(screen.getByText("No ticket required")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "On a schedule" })).toHaveAttribute("href", "/scheduled-jobs");
    expect(screen.getByRole("link", { name: "When an event happens" })).toHaveAttribute("href", "/automation/schedules");
    expect(screen.getByRole("link", { name: "Design a solution" })).toHaveAttribute("href", "/consultant");
    expect(screen.getByRole("link", { name: "Playbooks" })).toHaveAttribute("href", "/playbooks");
    expect(screen.getByText(/qbr-review, automation-opportunity-review, recurring-service-review/)).toBeInTheDocument();
  });
});
