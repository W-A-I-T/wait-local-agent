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
  Files,
  LibraryBig,
  ShieldCheck,
  Sparkles,
  Workflow
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useDashboard } from "./DashboardContext";

const navigation = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/connectors", label: "Connectors", icon: GitBranch },
  { to: "/tickets", label: "Tickets", icon: ClipboardList },
  { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/technician-chat", label: "Technician Chat", icon: MessageSquare },
  { to: "/backfills", label: "Backfills", icon: ListChecks },
  { to: "/executions", label: "Executions", icon: Activity },
  { to: "/knowledge", label: "Knowledge", icon: BookOpenText },
  { to: "/workflows", label: "Workflows", icon: Workflow },
  { to: "/workflow-designer", label: "Workflow Designer", icon: Workflow },
  { to: "/templates", label: "Templates", icon: Files },
  { to: "/playbooks", label: "Playbooks", icon: LibraryBig },
  { to: "/consultant", label: "Consultant", icon: Compass },
  { to: "/collectors", label: "Collectors", icon: Database },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/audit", label: "Audit", icon: FileSearch },
  { to: "/scheduled-jobs", label: "Scheduled Jobs", icon: CalendarClock },
  { to: "/founder", label: "Founder", icon: Sparkles }
];

const systemNavigation = [
  { to: "/settings", label: "Settings", icon: Activity }
];

export function Sidebar() {
  const { isAdmin } = useDashboard();

  return (
    <aside className="sidebar" aria-label="Workspace navigation">
      <div className="brand">
        <ShieldCheck size={28} aria-hidden="true" />
        <div>
          <strong>WAIT Local Agent</strong>
          <span>Consultant and MSP runtime</span>
        </div>
      </div>
      <nav>
        {navigation.map(({ to, label, icon: Icon }) => (
          <NavLink
            end={to === "/"}
            key={to}
            to={to}
            className={({ isActive }) => isActive ? "active" : undefined}
          >
            <Icon size={18} aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      </nav>
      <section className="sidebar-system" aria-label="System">
        <span className="sidebar-section-label">System</span>
        <nav aria-label="System navigation">
          {systemNavigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => isActive ? "active" : undefined}>
              <Icon size={18} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
          {isAdmin ? (
            <NavLink to="/system/appliance-health" className={({ isActive }) => isActive ? "active" : undefined}>
              <ShieldCheck size={18} aria-hidden="true" />
              Appliance Health
            </NavLink>
          ) : null}
        </nav>
      </section>
    </aside>
  );
}
