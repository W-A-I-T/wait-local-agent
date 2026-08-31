import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Bot,
  BarChart3,
  BookOpenText,
  ClipboardCheck,
  ClipboardList,
  Compass,
  Database,
  FileSearch,
  GitBranch,
  LifeBuoy,
  LayoutDashboard,
  MessageSquare,
  Network,
  PackageOpen,
  ShieldCheck,
  Sparkles,
  Users,
  Workflow
} from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { useDashboard } from "./DashboardContext";
import { RoleGate } from "../components/RoleGate";
import { useMicrosoftAdminAccess } from "../hooks/useMicrosoftAdminAccess";

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  microsoftAdminCapability?: boolean;
  endUserSupport?: boolean;
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
      { to: "/technician-chat", label: "Technician Chat", icon: MessageSquare },
      { to: "/end-user", label: "End-user support", icon: LifeBuoy, endUserSupport: true },
      { to: "/microsoft-admin", label: "Microsoft Admin", icon: ShieldCheck, microsoftAdminCapability: true }
    ]
  },
  {
    label: "Control",
    items: [
      { to: "/connectors", label: "Connectors", icon: GitBranch },
      { to: "/workflows", label: "Automations", icon: Workflow },
      { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
      { to: "/executions", label: "Activity", icon: Activity },
      { to: "/audit", label: "Audit", icon: FileSearch },
      { to: "/reports", label: "Reports", icon: BarChart3 }
    ]
  },
  {
    label: "Workspace",
    items: [
      { to: "/knowledge", label: "Knowledge", icon: BookOpenText },
      { to: "/agents", label: "Agents", icon: Bot }
    ]
  },
  {
    label: "Solutions",
    items: [
      { to: "/m365-actions", label: "M365 Actions", icon: ShieldCheck },
      { to: "/microsoft-admin/azure-lighthouse", label: "Azure Lighthouse", icon: ShieldCheck, microsoftAdminCapability: true },
      { to: "/consultant", label: "Solutions Architect", icon: Compass },
      { to: "/consultant/solution-delivery", label: "Solution delivery", icon: PackageOpen }
    ]
  }
];

const advancedNavigation: NavItem[] = [
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/collectors", label: "Collectors", icon: Database },
  { to: "/founder", label: "Launch Passport", icon: Sparkles },
  { to: "/integrations/connector-instances", label: "Connector Instances", icon: Database, adminOnly: true },
  { to: "/microsoft-admin/access", label: "Microsoft Admin Access", icon: ShieldCheck, adminOnly: true },
  { to: "/settings", label: "Settings", icon: Activity },
  { to: "/operations/reconciliation", label: "Sync / Reconciliation", icon: Database, adminOnly: true },
  { to: "/system/appliance-health", label: "Appliance Health", icon: ShieldCheck, adminOnly: true },
  { to: "/system/extensions", label: "Extensions / Packs", icon: PackageOpen, adminOnly: true },
  { to: "/integrations/mcp", label: "MCP", icon: Network, adminOnly: true }
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
  const { role, roleResolved, endUserSupportEnabled, configurationSteps, configurationLoading, isConfigured } = useDashboard();
  const microsoftAdmin = useMicrosoftAdminAccess();
  const requiredSteps = (configurationSteps ?? []).filter((step) => step.required);
  const completedSteps = requiredSteps.filter((step) => step.status === "done").length;
  const setupIndicator = requiredSteps.length > 0 && (configurationLoading || !isConfigured)
    ? <Link className="sidebar-setup-indicator" to="/?onboarding=1">{configurationLoading ? "Setup: checking…" : `Setup: ${completedSteps} of ${requiredSteps.length}`}</Link>
    : null;

  const renderItem = (item: NavItem) => {
    if (item.endUserSupport && !endUserSupportEnabled) {
      return null;
    }
    if (item.microsoftAdminCapability && (!microsoftAdmin.resolved || !microsoftAdmin.navAllowed)) {
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
        {setupIndicator}
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
