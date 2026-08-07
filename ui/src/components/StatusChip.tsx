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
  failed: { label: "Didn't finish", tone: "danger" },
  running: { label: "Running", tone: "info" },
  connected: { label: "Connected", tone: "ok" },
  configured: { label: "Configured", tone: "ok" },
  available: { label: "Available", tone: "info" },
  not_configured: { label: "Not connected", tone: "neutral" },
  unreachable: { label: "Connection needs attention", tone: "warn" }
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
