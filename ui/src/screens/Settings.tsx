import { BookOpenText, KeyRound, ServerCog, Workflow } from "lucide-react";
import { useDashboard } from "../app/DashboardContext";

export function Settings() {
  const { isAdmin, writeHealth, isConfigured, configurationLoading } = useDashboard();

  if (!isAdmin) {
    return <section className="panel"><h2>Settings</h2><p>Administrator access is required for provider and secret details.</p></section>;
  }

  return (
    <section className="panel settings-panel">
      <div className="panel-heading">
        <h2>Provider And Secrets</h2>
        <span>{configurationLoading ? "checking" : isConfigured ? "configured" : "local env"}</span>
      </div>
      <dl className="settings-list">
        <div>
          <dt>Write gate</dt>
          <dd><ServerCog size={15} aria-hidden="true" />{writeHealth.message}</dd>
        </div>
        <div>
          <dt>Secrets</dt>
          <dd><KeyRound size={15} aria-hidden="true" />Redacted from API, CLI, and UI output</dd>
        </div>
        <div>
          <dt>Knowledge</dt>
          <dd><BookOpenText size={15} aria-hidden="true" />Local citations remain available for draft text</dd>
        </div>
        <div>
          <dt>Workflows</dt>
          <dd><Workflow size={15} aria-hidden="true" />Approval requests stay local until execution</dd>
        </div>
      </dl>
    </section>
  );
}
