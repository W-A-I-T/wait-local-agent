import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { AutomationDiscoveryPanel } from "./AutomationDiscoveryPanel";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
const mockedApiFetch = vi.mocked(apiFetch);
const dashboard = vi.hoisted(() => ({
  isAdmin: true,
  role: "admin" as const,
  roleResolved: true,
  selectedClientId: "acme",
  isMspAdmin: false,
  clients: [{ client_id: "acme", name: "Acme Support", status: "active" }]
}));

vi.mock("../app/DashboardContext", () => ({ useDashboard: () => dashboard }));

describe("AutomationDiscoveryPanel", () => {
  beforeEach(() => {
    dashboard.selectedClientId = "acme";
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/packs/automation-discovery/status") return Promise.resolve({ status: "ready", external_writes: false });
      if (path === "/packs/automation-discovery/categories") return Promise.resolve([]);
      if (path.includes("mapping-readiness")) return Promise.resolve({ client_id: "acme", families: {}, mappings: [], verified_count: 0, unverified_count: 0 });
      if (path.includes("historical")) return Promise.resolve({
        client_id: "acme", window_days: 60, ticket_count: 0, opportunity_count: 0, opportunities: [],
        labor: { measured_minutes: 0, measured: false, measured_ticket_count: 0, estimate_minutes: 0, estimate: true, derivation: "No evidence" },
        mapping_readiness: { verified_count: 0, unverified_count: 0, families: {} },
        side_effects: false, automation_enabled: false, next_step: "Review more evidence."
      });
      return Promise.resolve([]);
    });
  });

  it("uses the shell scope without rendering a second client selector", async () => {
    render(<MemoryRouter><AutomationDiscoveryPanel /></MemoryRouter>);

    expect(screen.queryByRole("combobox", { name: /client/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Analyze ticket history" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("client_id=acme")));
  });

  it("guides a bound principal when the shell scope is empty", () => {
    dashboard.selectedClientId = "";
    render(<MemoryRouter><AutomationDiscoveryPanel /></MemoryRouter>);

    expect(screen.getByText("Choose a client in the top bar to continue.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze ticket history" })).toBeDisabled();
  });
});
