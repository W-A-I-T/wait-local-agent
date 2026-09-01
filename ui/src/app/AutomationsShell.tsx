import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

export const automationTabs = [
  {
    to: "/workflows",
    label: "Run",
    description: "Start a reviewed workflow template against a ticket. Templates are code-reviewed and cannot be edited here."
  },
  {
    to: "/playbooks",
    label: "Playbooks",
    description: "Multi-step service workflows from the library. Publish a tenant copy to enable, preview, and run it."
  },
  {
    to: "/templates",
    label: "My templates",
    description: "Tenant-editable copies of workflow templates: rename, describe, enable, import/export, revisions."
  },
  {
    to: "/workflow-designer",
    label: "Designer",
    description: "Draw a design graph for a template copy. Designs are saved and versioned but do not change what runs yet."
  },
  {
    to: "/integrations/smart-actions",
    label: "Action catalog",
    description: "Every bounded action agents and workflows can use, with risk and approval requirements."
  }
] as const;

export function AutomationsShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const activeTab = automationTabs.find((tab) => tab.to === pathname) ?? automationTabs[0];

  return (
    <div className="automations-shell">
      <section className="panel automations-header">
        <div className="automations-heading">
          <div>
            <p className="eyebrow">Automation workspace</p>
            <h1>Automations</h1>
            <p className="automations-subtitle">{activeTab.label}</p>
          </div>
        </div>
        <nav className="automations-tabs" aria-label="Automation surfaces">
          {automationTabs.map((tab) => {
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
        <p className="automations-description">
          {activeTab.description}
          {activeTab.to === "/workflows" ? (
            <span className="automation-cross-link">
              {" "}
              <Link to="/executions">Run history → Activity</Link>
            </span>
          ) : null}
        </p>
      </section>
      {children}
    </div>
  );
}
