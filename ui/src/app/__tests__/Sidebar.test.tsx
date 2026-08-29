import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../Sidebar";
import { useDashboard } from "../DashboardContext";
import { useMicrosoftAdminAccess } from "../../hooks/useMicrosoftAdminAccess";

vi.mock("../DashboardContext", () => ({
  useDashboard: vi.fn()
}));
vi.mock("../../hooks/useMicrosoftAdminAccess", () => ({
  useMicrosoftAdminAccess: vi.fn()
}));

const mockedUseDashboard = vi.mocked(useDashboard);
const mockedMicrosoftAdminAccess = vi.mocked(useMicrosoftAdminAccess);

const destinations = [
  ["Overview", "/"], ["Clients", "/clients"],
  ["Tickets", "/tickets"], ["Approvals", "/approvals"], ["Technician Chat", "/technician-chat"], ["Microsoft Admin", "/microsoft-admin"], ["M365 Actions", "/m365-actions"],
  ["Playbooks", "/playbooks"], ["Workflows", "/workflows"], ["Agents", "/agents"], ["Smart Actions", "/integrations/smart-actions"], ["Events", "/automation/events"], ["Schedules", "/automation/schedules"],
  ["Solutions Architect", "/consultant"],
  ["Reports", "/reports"], ["Analytics", "/analytics"], ["Audit", "/audit"], ["Collectors", "/collectors"],
  ["Launch Passport", "/founder"],
  ["Connectors", "/connectors"], ["Connector Instances", "/integrations/connector-instances"], ["Microsoft Admin Access", "/microsoft-admin/access"], ["Knowledge", "/knowledge"], ["Settings", "/settings"],
  ["Sync / Reconciliation", "/operations/reconciliation"], ["Appliance Health", "/system/appliance-health"], ["Extensions / Packs", "/system/extensions"], ["MCP", "/integrations/mcp"], ["Workflow Designer", "/workflow-designer"], ["Templates", "/templates"], ["Scheduled Jobs", "/scheduled-jobs"], ["Smart Action Runs", "/smart-actions/runs"], ["Executions", "/executions"], ["Backfills", "/backfills"]
] as const;

function renderSidebar(role: "admin" | "viewer", microsoftAdminAllowed = true) {
  mockedUseDashboard.mockReturnValue({ role, roleResolved: true } as never);
  mockedMicrosoftAdminAccess.mockReturnValue({
    allowed: microsoftAdminAllowed,
    resolved: true,
    grants: [],
    error: "",
    refresh: vi.fn()
  });
  return render(<MemoryRouter><Sidebar /></MemoryRouter>);
}

describe("Sidebar navigation IA", () => {
  beforeEach(() => {
    mockedUseDashboard.mockReset();
    mockedMicrosoftAdminAccess.mockReset();
  });

  it("renders the product groups and keeps every destination path for an authorized admin", () => {
    renderSidebar("admin", true);

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

  it("hides Microsoft Admin until the selected client is explicitly granted", () => {
    renderSidebar("viewer", false);

    expect(screen.queryByRole("link", { name: "Microsoft Admin" })).not.toBeInTheDocument();
  });

  it("shows Microsoft Admin to a granted viewer but keeps access management admin-only", () => {
    renderSidebar("viewer", true);

    expect(screen.getByRole("link", { name: "Microsoft Admin" })).toHaveAttribute("href", "/microsoft-admin");
    expect(screen.queryByRole("link", { name: "Microsoft Admin Access" })).not.toBeInTheDocument();
  });

  it("keeps advanced admin links gated for viewers", () => {
    renderSidebar("viewer");
    fireEvent.click(screen.getByText("System / Advanced"));

    for (const label of ["Connector Instances", "Microsoft Admin Access", "Sync / Reconciliation", "Appliance Health", "Extensions / Packs", "MCP"]) {
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }

    for (const label of ["Workflow Designer", "Templates", "Scheduled Jobs", "Smart Action Runs", "Executions", "Backfills"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });
});
