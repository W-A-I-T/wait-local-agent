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
  ["Overview", "/"], ["Clients", "/clients"], ["Client discovery", "/client-discovery"],
  ["Tickets", "/tickets"], ["Approvals", "/approvals"], ["Technician Chat", "/technician-chat"], ["Technician Path", "/technician-path"], ["Microsoft Admin", "/microsoft-admin"], ["M365 Actions", "/m365-actions"], ["Azure Lighthouse", "/microsoft-admin/azure-lighthouse"],
  ["Automations", "/workflows"], ["Agents", "/agents"], ["Activity", "/activity/runs"],
  ["Solutions Architect", "/consultant"],
  ["Solution delivery", "/consultant/solution-delivery"],
  ["Reports", "/reports"], ["Analytics", "/analytics"], ["Audit", "/audit"], ["Collectors", "/collectors"],
  ["Launch Passport", "/founder"],
  ["Connectors", "/connectors"], ["Connector Instances", "/integrations/connector-instances"], ["Identity & Access", "/system/identity-access"], ["Microsoft Admin Access", "/microsoft-admin/access"], ["Knowledge", "/knowledge"], ["Settings", "/settings"],
  ["Sync / Reconciliation", "/operations/reconciliation"], ["Appliance Health", "/system/appliance-health"], ["Diagnostics & Support", "/system/diagnostics"], ["Extensions / Packs", "/system/extensions"], ["MCP", "/integrations/mcp"]
] as const;

const groupedDestinations = {
  Operations: [
    ["Tickets", "/tickets"], ["Technician Chat", "/technician-chat"], ["Technician Path", "/technician-path"], ["Microsoft Admin", "/microsoft-admin"]
  ],
  Control: [
    ["Connectors", "/connectors"], ["Automations", "/workflows"], ["Approvals", "/approvals"], ["Activity", "/activity/runs"], ["Audit", "/audit"], ["Reports", "/reports"]
  ],
  Workspace: [
    ["Knowledge", "/knowledge"], ["Agents", "/agents"]
  ],
  Solutions: [
    ["M365 Actions", "/m365-actions"], ["Azure Lighthouse", "/microsoft-admin/azure-lighthouse"], ["Solutions Architect", "/consultant"], ["Solution delivery", "/consultant/solution-delivery"]
  ]
} as const;

const advancedDestinations = [
  ["Analytics", "/analytics"], ["Collectors", "/collectors"], ["Launch Passport", "/founder"],
  ["Connector Instances", "/integrations/connector-instances"], ["Identity & Access", "/system/identity-access"], ["Microsoft Admin Access", "/microsoft-admin/access"], ["Settings", "/settings"], ["Sync / Reconciliation", "/operations/reconciliation"], ["Appliance Health", "/system/appliance-health"], ["Diagnostics & Support", "/system/diagnostics"], ["Extensions / Packs", "/system/extensions"], ["MCP", "/integrations/mcp"]
] as const;

function renderSidebar(
  role: "admin" | "viewer",
  microsoftAdminAllowed = true,
  microsoftAdminNavAllowed = microsoftAdminAllowed,
  endUserSupportEnabled = false
) {
  mockedUseDashboard.mockReturnValue({ role, roleResolved: true, endUserSupportEnabled } as never);
  mockedMicrosoftAdminAccess.mockReturnValue({
    allowed: microsoftAdminAllowed,
    navAllowed: microsoftAdminNavAllowed,
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

    const links = screen.getAllByRole("link");
    for (const [label, path] of destinations) {
      const matchingLinks = links.filter((link) => link.textContent?.trim() === label);
      expect(matchingLinks).toHaveLength(1);
      expect(matchingLinks[0]).toHaveAttribute("href", path);
    }
  }, 15000);

  it("renames Consultant without changing its route", () => {
    renderSidebar("admin");

    expect(screen.getByRole("link", { name: "Solutions Architect" })).toHaveAttribute("href", "/consultant");
    expect(screen.queryByRole("link", { name: "Consultant" })).not.toBeInTheDocument();
  });

  it("keeps Client discovery in the Clients navigation group", () => {
    renderSidebar("admin");

    const group = screen.getByRole("navigation", { name: "Overview and clients" });
    expect(within(group).getByRole("link", { name: "Client discovery" })).toHaveAttribute("href", "/client-discovery");
  });

  it("hides Microsoft Admin until the selected client is explicitly granted", () => {
    renderSidebar("viewer", false);

    expect(screen.queryByRole("link", { name: "Microsoft Admin" })).not.toBeInTheDocument();
  });

  it("shows the end-user support entry only when the surface is enabled", () => {
    renderSidebar("admin", true, true, true);

    const portalLink = screen.getByRole("link", { name: "End-user support" });
    expect(portalLink).toHaveAttribute("href", "/end-user");
    expect(portalLink).toHaveAttribute("target", "_blank");
    expect(portalLink).toHaveAttribute("rel", "noopener");
    expect(screen.getByText("Customer portal — separate sign-in")).toBeInTheDocument();
  });

  it("hides the end-user support entry when the surface is disabled", () => {
    renderSidebar("admin", true, true, false);

    expect(screen.queryByRole("link", { name: "End-user support" })).not.toBeInTheDocument();
  });

  it("shows the Microsoft Admin pack navigation for a client grant when All clients is selected", () => {
    renderSidebar("viewer", false, true);

    expect(screen.getByRole("link", { name: "Microsoft Admin" })).toHaveAttribute("href", "/microsoft-admin");
    expect(screen.getByRole("link", { name: "Azure Lighthouse" })).toHaveAttribute("href", "/microsoft-admin/azure-lighthouse");
  });

  it("shows Microsoft Admin to a granted viewer but keeps access management admin-only", () => {
    renderSidebar("viewer", true);

    expect(screen.getByRole("link", { name: "Microsoft Admin" })).toHaveAttribute("href", "/microsoft-admin");
    expect(screen.queryByRole("link", { name: "Microsoft Admin Access" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Identity & Access" })).not.toBeInTheDocument();
  });

  it("keeps incomplete setup reachable after the overview wizard is dismissed", () => {
    mockedUseDashboard.mockReturnValue({
      role: "admin",
      roleResolved: true,
      isConfigured: false,
      configurationLoading: false,
      configurationSteps: [
        { id: "admin", label: "Administrator account", status: "done", required: true },
        { id: "client", label: "Client created", status: "done", required: true },
        { id: "connector", label: "Operational connector configured", status: "todo", required: true },
        { id: "mapping", label: "Client mapping verified", status: "todo", required: true }
      ]
    } as never);
    mockedMicrosoftAdminAccess.mockReturnValue({
      allowed: true,
      navAllowed: true,
      resolved: true,
      grants: [],
      error: "",
      refresh: vi.fn()
    });

    render(<MemoryRouter><Sidebar /></MemoryRouter>);

    expect(screen.getByRole("link", { name: "Setup: 2 of 4" })).toHaveAttribute("href", "/?onboarding=1");
  });

  it("keeps advanced admin links gated for viewers", () => {
    renderSidebar("viewer");
    fireEvent.click(screen.getByText("System / Advanced"));

    for (const label of ["Connector Instances", "Identity & Access", "Microsoft Admin Access", "Settings", "Sync / Reconciliation", "Appliance Health", "Diagnostics & Support", "Extensions / Packs", "MCP"]) {
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }

    expect(screen.getByRole("link", { name: "Activity" })).toHaveAttribute("href", "/activity/runs");
    for (const label of ["Events", "Schedules", "Scheduled Jobs", "Smart Action Runs", "Executions", "Backfills"]) {
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
  });

  it("keeps the automation surfaces reachable only through the hub", () => {
    renderSidebar("admin");
    fireEvent.click(screen.getByText("System / Advanced"));

    expect(screen.getByRole("link", { name: "Automations" })).toHaveAttribute("href", "/workflows");
    for (const label of ["Workflow Designer", "Playbooks", "Smart Actions", "Templates"]) {
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
  });
});
