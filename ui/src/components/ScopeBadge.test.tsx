import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDashboard } from "../app/DashboardContext";
import { ScopeBadge } from "./ScopeBadge";

vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedUseDashboard = vi.mocked(useDashboard);

describe("ScopeBadge", () => {
  beforeEach(() => mockedUseDashboard.mockReset());

  it("shows appliance-wide scope for an MSP administrator with no selection", () => {
    mockedUseDashboard.mockReturnValue({
      role: "admin",
      isMspAdmin: true,
      clientScopeIds: [],
      selectedClientId: "",
      clients: []
    } as never);

    render(<ScopeBadge />);

    expect(screen.getByText("All clients")).toBeInTheDocument();
  });

  it("shows the selected client for a bound viewer", () => {
    mockedUseDashboard.mockReturnValue({
      role: "viewer",
      isMspAdmin: false,
      clientScopeIds: ["acme"],
      selectedClientId: "acme",
      clients: [{ client_id: "acme", name: "Acme Support" }]
    } as never);

    render(<ScopeBadge />);

    expect(screen.getByText("Scoped to Acme Support")).toBeInTheDocument();
  });

  it("guides a bound viewer when no client is selected", () => {
    mockedUseDashboard.mockReturnValue({
      role: "viewer",
      isMspAdmin: false,
      clientScopeIds: ["acme"],
      selectedClientId: "",
      clients: [{ client_id: "acme", name: "Acme Support" }]
    } as never);

    render(<ScopeBadge />);

    expect(screen.getByText("No client selected")).toBeInTheDocument();
  });
});
