import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMicrosoftAdminAccess } from "../hooks/useMicrosoftAdminAccess";

export function MicrosoftAdminCapabilityGate({ children }: { children: ReactNode }) {
  const { allowed, resolved, error } = useMicrosoftAdminAccess();

  if (!resolved) {
    return (
      <section className="panel" aria-live="polite">
        <h2>Checking Microsoft Admin access…</h2>
        <p className="screen-note">WAIT is verifying your capability grant for the selected client.</p>
      </section>
    );
  }

  if (!allowed) {
    return (
      <section className="panel" role="alert">
        <h2>Microsoft Admin access denied</h2>
        <p className="screen-note">
          Your account does not have the Microsoft Admin capability for the selected client.
        </p>
        {error ? <p className="screen-note">Access verification: {error}</p> : null}
        <Link to="/">Return to Overview</Link>
      </section>
    );
  }

  return <>{children}</>;
}
