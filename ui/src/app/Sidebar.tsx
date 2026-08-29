import type { LucideIcon } from "lucide-react";
import {
  Activity,
  ListChecks,
  Bot,
  BarChart3,
  BookOpenText,
  CalendarClock,
  ClipboardCheck,
  ClipboardList,
  Compass,
  Database,
  FileSearch,
  GitBranch,
  LayoutDashboard,
  MessageSquare,
  Network,
  Files,
  LibraryBig,
  PackageOpen,
  ShieldCheck,
  Sparkles,
  Users,
  Workflow
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useDashboard } from "./DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { useMicrosoftAdminAccess } from "../hooks/useMicrosoftAdminAccess";

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  microsoftAdminCapability?: boolean;
};

type NavigationGroup = {
  label?: string;
  items: NavItem[];
};

const primaryNavigation: NavigationGroup[] = [
  {
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard },
      { to: "/clients", label: "Clients", icon: Users }
    ]
  },
  {
    label: "Operations",
    items: [
      { to: "/tickets", label: "Tickets", icon: ClipboardList },
      { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
      { to: "/technician-chat", label: "Technician Chat", icon: MessageSquare },
      { to: "/microsoft-admin", label: "Microsoft Admin", icon: ShieldCheck, microsoftAdminCapability: true },
      { to: "/m365-actions", label: "M365 Actions", icon: ShieldCheck }
    ]
  },
  {
    label: "Automations",
    items: [
      { to: "/playbooks", label: "Playbooks", icon: LibraryBig },
      { to: "/workflows", label: "Workflows", icon: Workflow },
      { to: "/agents", label: "Agents", icon: Bot },
      { to: "/integrations/smart-actions", label: "Smart Actions", icon: Sparkles },
      { to: "/automation/events", label: "Events", icon: Activity },
      { to: "/automation/schedules", label: "Schedules", icon: CalendarClock }
    ]
  },
  {
    items: [{ to: "/consultant", label: "Solutions Architect", icon: Compass }]
  },
  {
    label: "Evidence & Reports",
    items: [
      { to: "/reports", label: "Reports", icon: BarChart3 },
      { to: "/analytics", label: "Analytics", icon: BarChart3 },
      { to: "/audit", label: "Audit", icon: FileSearch },
      { to: "/collectors", label: "Collectors", icon: Database }
    ]
  },
  {
    items: [{ to: "/founder", label: "Launch Passport", icon: Sparkles }]
  },
  {
    label: "Setup",
    items: [
      { to: "/connectors", label: "Connectors", icon: GitBranch },
      { to: "/integrations/connector-instances", label: "Connector Instances", icon: Database, adminOnly: true },
      { to: "/microsoft-admin/access", label: "Microsoft Admin Access", icon: ShieldCheck, adminOnly: true },
      { to: "/knowledge", label: "Knowledge", icon: BookOpenText },
      { to: "/settings", label: "Settings", icon: Activity }
    ]
  }
];

const advancedNavigation: NavItem[] = [
  { to: "/operations/reconciliation", label: "Sync / Reconciliation", icon: Database, adminOnly: true },
  { to: "/system/appliance-health", label: "Appliance Health", icon: ShieldCheck, adminOnly: true },
  { to: "/system/extensions", label: "Extensions / Packs", icon: PackageOpen, adminOnly: true },
  { to: "/integrations/mcp", label: "MCP", icon: Network, adminOnly: true },
  { to: "/workflow-designer", label: "Workflow Designer", icon: Workflow },
  { to: "/templates", label: "Templates", icon: Files },
  { to: "/scheduled-jobs", label: "Scheduled Jobs", icon: CalendarClock },
  { to: "/smart-actions/runs", label: "Smart Action Runs", icon: Activity },
  { to: "/executions", label: "Executions", icon: Activity },
  { to: "/backfills", label: "Backfills", icon: ListChecks }
];

function SidebarLink({ item }: { item: NavItem }) {
  const { to, label, icon: Icon } = item;
  return (
    <NavLink
      end={to === "/"}
      to={to}
      className={({ isActive }) => isActive ? "active" : undefined}
    >
      <Icon size={18} aria-hidden="true" />
      {label}
    </NavLink>
  );
}

export function Sidebar() {
  const { role, roleResolved } = useDashboard();
  const microsoftAdmin = useMicrosoftAdminAccess();

  const renderItem = (item: NavItem) => {
    if (item.microsoftAdminCapability && (!microsoftAdmin.resolved || !microsoftAdmin.allowed)) {
      return null;
    }
    const link = <SidebarLink key={item.to} item={item} />;
    return item.adminOnly
      ? <RoleGate key={item.to} role={role} resolved={roleResolved} allowed={["admin"]}>{link}</RoleGate>
      : link;
  };

  return (
    <aside className="sidebar" aria-label="Workspace navigation">
      <div className="brand">
        <ShieldCheck size={28} aria-hidden="true" />
        <div>
          <strong>WAIT Local Agent</strong>
          <span>MSP operations & automation</span>
        </div>
      </div>
      <nav aria-label="Primary navigation">
        {primaryNavigation.map((group, index) => (
          <section key={group.label ?? `primary-${index}`} aria-label={group.label ?? "Overview and clients"}>
            {group.label ? <span className="sidebar-section-label">{group.label}</span> : null}
            <nav aria-label={group.label ?? "Overview and clients"}>
              {group.items.map(renderItem)}
            </nav>
          </section>
        ))}
      </nav>
      <details className="sidebar-advanced">
        <summary className="sidebar-section-label">System / Advanced</summary>
        <nav aria-label="System and advanced navigation">
          {advancedNavigation.map(renderItem)}
        </nav>
      </details>
    </aside>
  );
}
