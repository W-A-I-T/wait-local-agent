import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

export const activityTabs = [
  {
    to: "/activity/runs",
    label: "All Runs",
    description: "Unified tenant-scoped history across executions and source run stores."
  },
  {
    to: "/automation/events",
    label: "Events",
    description: "Inbound events and their delivery to subscriptions."
  },
  {
    to: "/automation/schedules",
    label: "Schedules",
    description: "Recurring automation subscriptions and their status."
  },
  {
    to: "/scheduled-jobs",
    label: "Scheduled Jobs",
    description: "Cron / interval / one-time jobs that run templates, agents, or reports."
  },
  {
    to: "/smart-actions/runs",
    label: "Smart Action Runs",
    description: "History of individual bounded action invocations."
  },
  {
    to: "/executions",
    label: "Executions",
    description: "Canonical workflow and agent execution records with step and artifact detail."
  },
  {
    to: "/backfills",
    label: "Backfills",
    description: "Bulk re-runs of an agent across historical tickets."
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
            <h1>Activity &amp; scheduling</h1>
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
