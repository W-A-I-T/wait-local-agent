import { Activity, CheckCircle2, GitBranch, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useDashboard } from "../app/DashboardContext";
import { OnboardingWizard } from "../surfaces/onboarding/OnboardingWizard";

const ONBOARDING_DISMISS_KEY = "wait-local-agent-onboarding-dismissed";

export function Overview() {
  const {
    connectors,
    liveWritesReady,
    writeHealth,
    workflowRuns,
    eventHistory,
    isConfigured,
    configurationLoading
  } = useDashboard();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showOnboarding, setShowOnboarding] = useState(false);

  const shouldShowOnboarding = !configurationLoading && (searchParams.get("onboarding") === "1" || !isConfigured);

  useEffect(() => {
    if (!shouldShowOnboarding) {
      setShowOnboarding(false);
      return;
    }
    const dismissed = window.localStorage.getItem(ONBOARDING_DISMISS_KEY) === "1";
    setShowOnboarding(!dismissed);
  }, [shouldShowOnboarding]);

  function dismissOnboarding() {
    window.localStorage.setItem(ONBOARDING_DISMISS_KEY, "1");
    const next = new URLSearchParams(searchParams);
    next.delete("onboarding");
    setSearchParams(next, { replace: true });
    setShowOnboarding(false);
  }

  return (
    <div className="screen-stack">
      {showOnboarding ? (
        <section className="modal-backdrop">
          <div className="onboarding-modal">
            <OnboardingWizard onDone={() => dismissOnboarding()} onDismiss={() => dismissOnboarding()} />
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading">
          <h2>Operations Overview</h2>
          <span>{configurationLoading ? "checking configuration" : isConfigured ? "configured" : "demo-ready"}</span>
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
      </div>

      <p className="screen-note">
        <Activity size={16} aria-hidden="true" />
        Use the sidebar to move between live operations without losing the API token or role.
      </p>
    </div>
  );
}
