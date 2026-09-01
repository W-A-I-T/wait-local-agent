import { Activity, CheckCircle2, GitBranch, Sparkles, Workflow } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useDashboard } from "../app/DashboardContext";
import { SetupStatus } from "../components/SetupStatus";
import { OnboardingWizard } from "../surfaces/onboarding/OnboardingWizard";

const ONBOARDING_DISMISS_KEY = "wait-local-agent-onboarding-dismissed";

export function Overview() {
  const {
    connectors,
    liveWritesReady,
    writeHealth,
    workflowRuns,
    eventHistory,
    eventDeliveries,
    retryEventDelivery,
    canWrite,
    isConfigured,
    configurationLoading,
    roleResolved
  } = useDashboard();
  const [searchParams, setSearchParams] = useSearchParams();
  const [onboardingDismissed, setOnboardingDismissed] = useState(
    () => window.localStorage.getItem(ONBOARDING_DISMISS_KEY) === "1"
  );
  const requestedOnboardingStep = Number.parseInt(searchParams.get("step") ?? "0", 10);
  const onboardingStep = Number.isFinite(requestedOnboardingStep) ? requestedOnboardingStep : 0;

  const explicitlyRequested = searchParams.get("onboarding") === "1";
  const showOnboarding = roleResolved && !configurationLoading && (
    explicitlyRequested || (!isConfigured && !onboardingDismissed)
  );

  function dismissOnboarding() {
    window.localStorage.setItem(ONBOARDING_DISMISS_KEY, "1");
    setOnboardingDismissed(true);
    const next = new URLSearchParams(searchParams);
    next.delete("onboarding");
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="screen-stack">
      {showOnboarding ? (
        <section className="modal-backdrop">
          <div className="onboarding-modal">
            <OnboardingWizard
              initialStep={onboardingStep}
              onDone={() => dismissOnboarding()}
              onDismiss={() => dismissOnboarding()}
            />
          </div>
        </section>
      ) : null}

      {!showOnboarding ? <SetupStatus /> : null}

      <section className="panel">
        <div className="panel-heading">
          <h2>Operations Overview</h2>
          <span>
            {configurationLoading
              ? "checking configuration"
              : !roleResolved
                ? "access unavailable"
                : isConfigured
                  ? "configured"
                  : "demo-ready"}
          </span>
        </div>
        <div className="overview-cards">
          <Link className="overview-card" to="/connectors">
            <GitBranch size={20} aria-hidden="true" />
            <strong>{connectors.length} connectors</strong>
            <span>Review readiness and write gates</span>
          </Link>
          <Link className="overview-card" to="/tickets">
            <CheckCircle2 size={20} aria-hidden="true" />
            <strong>{liveWritesReady ? "Writes ready" : "Writes gated"}</strong>
            <span>{writeHealth.message}</span>
          </Link>
          <Link className="overview-card" to="/approvals">
            <Workflow size={20} aria-hidden="true" />
            <strong>{workflowRuns.length} workflow runs</strong>
            <span>Open the approval queue to review actions</span>
          </Link>
          <section className="overview-card" aria-labelledby="automate-something-heading">
            <Sparkles size={20} aria-hidden="true" />
            <strong id="automate-something-heading">Automate something</strong>
            <span>No ticket required</span>
            <nav className="overview-automation-links" aria-label="No-ticket automation">
              <Link to="/scheduled-jobs">On a schedule</Link>
              <Link to="/automation/schedules">When an event happens</Link>
              <Link to="/consultant">Design a solution</Link>
            </nav>
            <p className="overview-card-note">
              Report-only playbooks (qbr-review, automation-opportunity-review, recurring-service-review) run with just a client via{" "}
              <Link to="/playbooks">Playbooks</Link>.
            </p>
          </section>
        </div>
      </section>

      <div className="grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Workflow Runs</h2>
            <span>{workflowRuns.length} visible</span>
          </div>
          <div className="event-list">
            {workflowRuns.map((run) => (
              <div className="event-row" key={run.id}>
                <span>{run.goal || `Run ${run.id}`}</span>
                <strong>{run.approval_request_id ? `Approval ${run.approval_request_id}` : String(run.id)}</strong>
                <em>{run.status}</em>
                <p>{run.message || run.updated_at || run.created_at || "No run detail available."}</p>
              </div>
            ))}
            {workflowRuns.length === 0 ? <p>No workflow runs visible.</p> : null}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>Event History</h2>
            <span>{eventHistory.length} events</span>
          </div>
          <div className="event-list">
            {eventHistory.map((event) => (
              <div className="event-row" key={event.id}>
                <span>{event.event_type}</span>
                <strong>{event.subject_id}</strong>
                <em>{event.status}</em>
                <p>{event.message}</p>
              </div>
            ))}
            {eventHistory.length === 0 ? <p>No event history visible.</p> : null}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>Automation delivery retries</h2>
            <span>{eventDeliveries.length} deliveries</span>
          </div>
          <div className="event-list">
            {eventDeliveries.map((delivery) => {
              const retryable = delivery.status === "failed" && delivery.retry_count < delivery.max_retries;
              return (
                <article className="event-row" key={delivery.id}>
                  <span>{delivery.event_type}</span>
                  <strong>{delivery.entity_id}</strong>
                  <em>{delivery.status}</em>
                  <p>
                    Attempt {delivery.retry_count} of {delivery.max_retries}.
                    {delivery.error_detail ? ` ${delivery.error_detail}` : ""}
                    {delivery.next_retry_at ? ` Next retry: ${delivery.next_retry_at}.` : ""}
                  </p>
                  {retryable ? (
                    <button
                      type="button"
                      className="icon-button"
                      disabled={!canWrite}
                      onClick={() => void retryEventDelivery(delivery.id)}
                    >
                      Retry event delivery {delivery.id}
                    </button>
                  ) : null}
                </article>
              );
            })}
            {eventDeliveries.length === 0 ? <p>No automation deliveries visible.</p> : null}
          </div>
          {!canWrite && eventDeliveries.some((delivery) => delivery.status === "failed") ? (
            <p className="screen-note">Technician or administrator access is required to retry a failed delivery.</p>
          ) : null}
        </section>
      </div>

      <p className="screen-note">
        <Activity size={16} aria-hidden="true" />
        Use the sidebar to move between live operations without losing the API token or role.
      </p>
    </div>
  );
}
