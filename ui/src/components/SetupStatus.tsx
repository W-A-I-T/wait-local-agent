import { useDashboard } from "../app/DashboardContext";
import type { ReadinessStep } from "../api/types";

const MARKERS: Record<ReadinessStep["status"], string> = {
  done: "✓",
  todo: "✗",
  info: "○"
};

export function SetupStatus() {
  const { configurationSteps, isConfigured } = useDashboard();
  const remaining = configurationSteps.filter((step) => step.required && step.status !== "done").length;

  return (
    <section className="panel setup-status" aria-labelledby="setup-status-heading">
      <div className="panel-heading">
        <h2 id="setup-status-heading">Setup status</h2>
        <span>{isConfigured ? "ready" : "in progress"}</span>
      </div>
      <ul className="setup-status-list">
        {configurationSteps.map((step) => (
          <li key={step.id} className={`setup-status-item ${step.status}`}>
            <span className="setup-status-marker" aria-hidden="true">{MARKERS[step.status]}</span>
            <span>
              <strong>{step.label}</strong>
              {step.detail ? <small>{step.detail}</small> : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="setup-status-summary">
        {remaining === 0 ? "Setup complete" : `Setup: ${remaining} required step${remaining === 1 ? "" : "s"} remaining`}
      </p>
    </section>
  );
}
