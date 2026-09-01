import { useDashboard } from "../app/DashboardContext";
import type { ReadinessStep } from "../api/types";

const MARKERS: Record<ReadinessStep["status"], string> = {
  done: "✓",
  todo: "✗",
  info: "○"
};

export function SetupStatus() {
  const { configurationSteps, configurationLoading, isConfigured, roleResolved } = useDashboard();
  const remaining = configurationSteps.filter((step) => step.required && step.status !== "done").length;
  const setupResolved = roleResolved && !configurationLoading;
  const firstIncomplete = configurationSteps.find((step) => step.required && step.status !== "done");
  const onboardingStep = firstIncomplete?.id === "client"
    ? 0
    : firstIncomplete?.id === "connector"
      ? 1
      : firstIncomplete?.id === "mapping"
        ? 2
        : 0;

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
        {setupResolved
          ? remaining === 0
            ? "Setup complete"
            : `Setup: ${remaining} required step${remaining === 1 ? "" : "s"} remaining`
          : "Checking setup status…"}
      </p>
      {remaining > 0 ? <a className="secondary-button" href={`/?onboarding=1&step=${onboardingStep}`}>Open setup guide</a> : null}
    </section>
  );
}
