import type { LucideIcon } from "lucide-react";
import {
  Activity,
  ClipboardCheck,
  Compass,
  Database,
  GitBranch,
  LayoutDashboard,
  Network,
  PackageOpen,
  ShieldCheck,
  Stethoscope,
  Settings as SettingsIcon,
  Users,
  Workflow
} from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { useDashboard } from "./DashboardContext";
import { RoleGate } from "../components/RoleGate";

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  mspAdminOnly?: boolean;
};

type NavigationGroup = {
  label?: string;
  items: NavItem[];
};

const primaryNavigation: NavigationGroup[] = [
  {
    label: "Overview",
    items: [{ to: "/", label: "Overview", icon: LayoutDashboard }]
  },
  {
    label: "Clients",
    items: [
      { to: "/clients", label: "Clients", icon: Users },
      { to: "/client-discovery", label: "Client discovery", icon: Compass }
    ]
  },
  {
    label: "Connect",
    items: [
      { to: "/connectors", label: "Connectors", icon: GitBranch },
      { to: "/integrations/connector-instances", label: "Connector instances", icon: Database, adminOnly: true }
    ]
  },
  {
    label: "Automate",
    items: [{ to: "/workflows", label: "Automations", icon: Workflow }]
  },
  {
    label: "Approve",
    items: [{ to: "/approvals", label: "Approvals", icon: ClipboardCheck }]
  },
  {
    label: "Activity",
    items: [{ to: "/activity/runs", label: "Activity", icon: Activity }]
  },
  {
    label: "Solutions",
    items: [
      { to: "/consultant", label: "Solutions Architect", icon: Compass },
      { to: "/consultant/solution-delivery", label: "Solution delivery", icon: PackageOpen }
    ]
  },
  {
    label: "Settings",
    items: [
      { to: "/settings", label: "Settings", icon: SettingsIcon, adminOnly: true },
      { to: "/settings/access", label: "People & Access", icon: Users, mspAdminOnly: true },
      { to: "/system/appliance-health", label: "Appliance health", icon: ShieldCheck, adminOnly: true },
      { to: "/system/diagnostics", label: "Diagnostics", icon: Stethoscope, adminOnly: true }
    ]
  }
];

const advancedNavigation: NavItem[] = [
  { to: "/system/extensions", label: "Extensions", icon: PackageOpen, adminOnly: true },
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
  const { role, roleResolved, isMspAdmin, configurationSteps, configurationLoading, isConfigured } = useDashboard();
  const requiredSteps = (configurationSteps ?? []).filter((step) => step.required);
  const completedSteps = requiredSteps.filter((step) => step.status === "done").length;
  const setupIndicator = requiredSteps.length > 0 && (configurationLoading || !isConfigured)
    ? <Link className="sidebar-setup-indicator" to="/?onboarding=1">{configurationLoading ? "Setup: checking…" : `Setup: ${completedSteps} of ${requiredSteps.length}`}</Link>
    : null;

  const renderItem = (item: NavItem) => {
    if (item.mspAdminOnly && (!roleResolved || !isMspAdmin)) {
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
        <summary className="sidebar-section-label">Advanced</summary>
        <nav aria-label="Advanced navigation">
          {advancedNavigation.map(renderItem)}
        </nav>
      </details>
    </aside>
  );
}
