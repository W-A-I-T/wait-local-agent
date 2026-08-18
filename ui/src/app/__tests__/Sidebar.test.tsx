import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../Sidebar";
import { useDashboard } from "../DashboardContext";

vi.mock("../DashboardContext", () => ({
  useDashboard: vi.fn()
}));

const mockedUseDashboard = vi.mocked(useDashboard);

const destinations = [
  ["Overview", "/"], ["Clients", "/clients"],
  ["Tickets", "/tickets"], ["Approvals", "/approvals"], ["Technician Chat", "/technician-chat"], ["M365 Actions", "/m365-actions"],
  ["Playbooks", "/playbooks"], ["Workflows", "/workflows"], ["Agents", "/agents"], ["Smart Actions", "/integrations/smart-actions"], ["Events", "/automation/events"], ["Schedules", "/automation/schedules"],
  ["Solutions Architect", "/consultant"],
  ["Reports", "/reports"], ["Analytics", "/analytics"], ["Audit", "/audit"], ["Collectors", "/collectors"],
  ["Launch Passport", "/founder"],
  ["Connectors", "/connectors"], ["Connector Instances", "/integrations/connector-instances"], ["Knowledge", "/knowledge"], ["Settings", "/settings"],
  ["Sync / Reconciliation", "/operations/reconciliation"], ["Appliance Health", "/system/appliance-health"], ["Extensions / Packs", "/system/extensions"], ["MCP", "/integrations/mcp"], ["Workflow Designer", "/workflow-designer"], ["Templates", "/templates"], ["Scheduled Jobs", "/scheduled-jobs"], ["Smart Action Runs", "/smart-actions/runs"], ["Executions", "/executions"], ["Backfills", "/backfills"]
] as const;

function renderSidebar(role: "admin" | "viewer") {
  mockedUseDashboard.mockReturnValue({ role, roleResolved: true } as never);
  return render(<MemoryRouter><Sidebar /></MemoryRouter>);
}

describe("Sidebar navigation IA", () => {
  beforeEach(() => {
    mockedUseDashboard.mockReset();
  });

  it("renders the product groups and keeps every destination path", () => {
    renderSidebar("admin");

    expect(screen.getByText("Operations")).toBeInTheDocument();
    expect(screen.getByText("Automations")).toBeInTheDocument();
    expect(screen.getByText("Evidence & Reports")).toBeInTheDocument();
    expect(screen.getByText("Setup")).toBeInTheDocument();

    const advanced = screen.getByText("System / Advanced");
    expect(advanced.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(advanced);

    for (const [label, path] of destinations) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", path);
    }
  });

  it("renames Consultant without changing its route", () => {
    renderSidebar("admin");

    expect(screen.getByRole("link", { name: "Solutions Architect" })).toHaveAttribute("href", "/consultant");
    expect(screen.queryByRole("link", { name: "Consultant" })).not.toBeInTheDocument();
  });

  it("keeps advanced admin links gated for viewers", () => {
    renderSidebar("viewer");
    fireEvent.click(screen.getByText("System / Advanced"));

    for (const label of ["Connector Instances", "Sync / Reconciliation", "Appliance Health", "Extensions / Packs", "MCP"]) {
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }

    for (const label of ["Workflow Designer", "Templates", "Scheduled Jobs", "Smart Action Runs", "Executions", "Backfills"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });
});
