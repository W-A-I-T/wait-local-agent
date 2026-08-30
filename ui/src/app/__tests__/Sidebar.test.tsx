import { fireEvent, render, screen, within } from "@testing-library/react";
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

const groupedDestinations = {
  Operations: [
    ["Tickets", "/tickets"], ["Technician Chat", "/technician-chat"], ["Microsoft Admin", "/microsoft-admin"]
  ],
  Control: [
    ["Connectors", "/connectors"], ["Workflows", "/workflows"], ["Approvals", "/approvals"], ["Executions", "/executions"], ["Audit", "/audit"], ["Reports", "/reports"]
  ],
  Workspace: [
    ["Knowledge", "/knowledge"], ["Schedules", "/automation/schedules"], ["Workflow Designer", "/workflow-designer"], ["Agents", "/agents"]
  ],
  Solutions: [
    ["M365 Actions", "/m365-actions"], ["Solutions Architect", "/consultant"]
  ]
} as const;

const advancedDestinations = [
  ["Playbooks", "/playbooks"], ["Smart Actions", "/integrations/smart-actions"], ["Events", "/automation/events"], ["Analytics", "/analytics"], ["Collectors", "/collectors"], ["Launch Passport", "/founder"],
  ["Connector Instances", "/integrations/connector-instances"], ["Microsoft Admin Access", "/microsoft-admin/access"], ["Settings", "/settings"], ["Sync / Reconciliation", "/operations/reconciliation"], ["Appliance Health", "/system/appliance-health"], ["Extensions / Packs", "/system/extensions"], ["MCP", "/integrations/mcp"], ["Templates", "/templates"], ["Scheduled Jobs", "/scheduled-jobs"], ["Smart Action Runs", "/smart-actions/runs"], ["Backfills", "/backfills"]
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

    for (const [group, links] of Object.entries(groupedDestinations)) {
      const section = screen.getByText(group).closest("section");
      expect(section).not.toBeNull();
      if (!section) throw new Error(`Missing navigation group: ${group}`);
      for (const [label, path] of links) {
        expect(within(section).getByRole("link", { name: label })).toHaveAttribute("href", path);
      }
    }

    const advanced = screen.getByText("System / Advanced");
    const drawer = advanced.closest("details");
    expect(drawer).not.toBeNull();
    if (!drawer) throw new Error("Missing System / Advanced drawer");
    expect(drawer).not.toHaveAttribute("open");
    fireEvent.click(advanced);

    for (const [label, path] of advancedDestinations) {
      expect(within(drawer).getByRole("link", { name: label })).toHaveAttribute("href", path);
    }

    for (const [label, path] of destinations) {
      expect(screen.getAllByRole("link", { name: label })).toHaveLength(1);
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
