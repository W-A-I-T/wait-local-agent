import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../Sidebar";
import { useDashboard } from "../DashboardContext";

vi.mock("../DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedUseDashboard = vi.mocked(useDashboard);

function renderSidebar(role: "admin" | "viewer" = "admin", isMspAdmin = true) {
  mockedUseDashboard.mockReturnValue({ role, roleResolved: true, isMspAdmin } as never);
  return render(<MemoryRouter><Sidebar /></MemoryRouter>);
}

describe("Sidebar navigation IA", () => {
  beforeEach(() => mockedUseDashboard.mockReset());

  it("renders groups in the operator journey order", () => {
    renderSidebar();
    const labels = Array.from(document.querySelectorAll(".sidebar-section-label"))
      .map((element) => element.textContent);
    expect(labels).toEqual(["Overview", "Clients", "Connect", "Automate", "Approve", "Activity", "Solutions", "Settings", "Advanced"]);
  });

  it("keeps connectors and connector instances in the Connect group", () => {
    renderSidebar();
    const group = screen.getByText("Connect").closest("section");
    expect(group).not.toBeNull();
    if (!group) throw new Error("Missing Connect group");
    expect(within(group).getByRole("link", { name: "Connectors" })).toHaveAttribute("href", "/connectors");
    expect(within(group).getByRole("link", { name: "Connector instances" })).toHaveAttribute("href", "/integrations/connector-instances");
  });

  it("limits the Advanced disclosure to extensions and MCP", () => {
    renderSidebar();
    const summary = screen.getByText("Advanced");
    const drawer = summary.closest("details");
    expect(drawer).not.toBeNull();
    if (!drawer) throw new Error("Missing Advanced disclosure");
    fireEvent.click(summary);
    expect(within(drawer).getByRole("link", { name: "Extensions" })).toHaveAttribute("href", "/system/extensions");
    expect(within(drawer).getByRole("link", { name: "MCP" })).toHaveAttribute("href", "/integrations/mcp");
    expect(drawer.querySelectorAll("a")).toHaveLength(2);
  });

  it("gates administrator settings for viewers", () => {
    renderSidebar("viewer", false);
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "People & Access" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Advanced"));
    expect(screen.queryByRole("link", { name: "Extensions" })).not.toBeInTheDocument();
  });
});
