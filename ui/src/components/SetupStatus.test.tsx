import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SetupStatus } from "./SetupStatus";

const mockUseDashboard = vi.hoisted(() => vi.fn());

vi.mock("../app/DashboardContext", () => ({
  useDashboard: mockUseDashboard
}));

describe("SetupStatus", () => {
  it("renders accessible markers and the remaining-step summary", () => {
    mockUseDashboard.mockReturnValue({
      isConfigured: false,
      configurationSteps: [
        { id: "admin", label: "Administrator account", status: "done", required: true },
        { id: "client", label: "Client created", status: "done", required: true },
        { id: "mapping", label: "Client mapping verified", status: "todo", required: true },
        { id: "writes", label: "Writes disabled safely", status: "info", required: false }
      ]
    });

    render(<SetupStatus />);

    expect(screen.getByRole("heading", { name: "Setup status" })).toBeInTheDocument();
    expect(screen.getAllByText("✓")).toHaveLength(2);
    expect(screen.getByText("✗")).toBeInTheDocument();
    expect(screen.getByText("○")).toBeInTheDocument();
    expect(screen.getByText("Setup: 1 required step remaining")).toBeInTheDocument();
  });

  it("renders setup complete when no required steps remain", () => {
    mockUseDashboard.mockReturnValue({
      isConfigured: true,
      configurationSteps: [{ id: "admin", label: "Administrator account", status: "done", required: true }]
    });

    render(<SetupStatus />);

    expect(screen.getByText("Setup complete")).toBeInTheDocument();
  });
});
