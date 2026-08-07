import { humanizeName } from "../lib/fields";

type StatusChipProps = {
  status?: string | null;
  hint?: string | null;
};

const STATUS_COPY: Record<string, { label: string; tone: string }> = {
  success: { label: "Working", tone: "ok" },
  empty: { label: "Nothing found", tone: "neutral" },
  partial: { label: "Partly collected", tone: "warn" },
  not_authorized: { label: "No permission — check the credentials", tone: "danger" },
  unavailable: { label: "Couldn't reach it", tone: "danger" },
  completed: { label: "Done", tone: "ok" },
  failed: { label: "Failed — needs attention", tone: "danger" },
  running: { label: "Running", tone: "info" },
  connected: { label: "Connected", tone: "ok" },
  configured: { label: "Configured", tone: "ok" },
  available: { label: "Available", tone: "info" },
  upload_only: { label: "Upload only", tone: "neutral" },
  not_configured: { label: "Not connected", tone: "neutral" },
  unreachable: { label: "Connection needs attention", tone: "warn" },
  passed: { label: "Passed", tone: "ok" },
  not_applicable: { label: "Not applicable", tone: "neutral" },
  error: { label: "Couldn't finish", tone: "danger" },
  evidence_loading: { label: "Loading evidence", tone: "info" },
  evidence_not_run: { label: "Not run yet", tone: "neutral" },
  evidence_no_evidence: { label: "No evidence recorded", tone: "danger" },
  evidence_partial: { label: "Needs attention", tone: "warn" },
  evidence_completed: { label: "Checks completed", tone: "ok" },
  evidence_unavailable: { label: "Evidence unavailable", tone: "danger" }
};

export function StatusChip({ status, hint }: StatusChipProps) {
  const known = status ? STATUS_COPY[status] : undefined;
  const label = known?.label ?? (status ? humanizeName(status) : "No status yet");
  const tone = known?.tone ?? "neutral";
  return (
    <span className="status-chip-wrap">
      <span className={`status-chip ${tone}`} title={hint ?? undefined}>
        {label}
      </span>
      {hint ? <span className="status-chip-detail">{hint}</span> : null}
    </span>
  );
}

export function ScopeChip({ scope }: { scope?: string | null }) {
  if (scope === "host") {
    return <span className="status-chip info">Collected from this computer</span>;
  }
  if (scope === "container") {
    return <span className="status-chip warn">Collected from inside the app's container</span>;
  }
  return null;
}
