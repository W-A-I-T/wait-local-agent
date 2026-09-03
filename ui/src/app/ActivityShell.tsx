import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

export const activityTabs = [
  {
    to: "/activity/runs",
    label: "Runs",
    description: "Unified client-scoped history across workflow, execution, smart action, scheduled, and backfill records."
  },
  {
    to: "/approvals",
    label: "Approvals",
    description: "Review and decide actions that are waiting for operator approval."
  },
  {
    to: "/audit",
    label: "Audit",
    description: "Review the tamper-evident record of operator and automation activity."
  }
] as const;

export function ActivityShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const activeTab = activityTabs.find((tab) => tab.to === pathname) ?? activityTabs[0];

  return (
    <div className="automations-shell">
      <section className="panel automations-header">
        <div className="automations-heading">
          <div>
            <p className="eyebrow">Activity workspace</p>
            <h1>Activity</h1>
            <p className="automations-subtitle">{activeTab.label}</p>
          </div>
        </div>
        <nav className="automations-tabs" aria-label="Activity and scheduling surfaces">
          {activityTabs.map((tab) => {
            const isActive = tab.to === activeTab.to;
            return (
              <Link
                key={tab.to}
                to={tab.to}
                className={isActive ? "active" : undefined}
                aria-current={isActive ? "page" : undefined}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>
        <p className="automations-description">{activeTab.description}</p>
      </section>
      {children}
    </div>
  );
}
