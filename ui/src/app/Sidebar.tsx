import {
  Activity,
  BarChart3,
  BookOpenText,
  CalendarClock,
  ClipboardCheck,
  ClipboardList,
  Database,
  FileSearch,
  GitBranch,
  LayoutDashboard,
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
  { to: "/knowledge", label: "Knowledge", icon: BookOpenText },
  { to: "/workflows", label: "Workflows", icon: Workflow },
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
          <span>Local MSP appliance</span>
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
