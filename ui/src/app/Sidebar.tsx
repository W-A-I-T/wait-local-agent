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
  ShieldCheck,
  Sparkles,
  Workflow
} from "lucide-react";
import { NavLink } from "react-router-dom";

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
  { to: "/consultant", label: "Consultant", icon: Compass },
  { to: "/collectors", label: "Collectors", icon: Database },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/audit", label: "Audit", icon: FileSearch },
  { to: "/scheduled-jobs", label: "Scheduled Jobs", icon: CalendarClock },
  { to: "/settings", label: "Settings", icon: Activity },
  { to: "/founder", label: "Founder", icon: Sparkles }
];

export function Sidebar() {
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
    </aside>
  );
}
