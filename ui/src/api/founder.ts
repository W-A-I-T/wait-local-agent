import type {
  FounderResults,
  FounderScanState,
  FounderScanView,
  FounderUploadPreview,
  LaunchPassportStatus
} from "./types";

const CONNECTION_STATES = new Set<LaunchPassportStatus["status"]>(["connected", "unreachable", "not_authorized", "unknown"]);
const SCAN_STATES = new Set<FounderScanState>([
  "queued",
  "pending",
  "pending_upload",
  "running",
  "completed",
  "uploaded",
  "failed",
  "cancelled",
  "unknown"
]);
const POLLING_STATES = new Set<NonNullable<LaunchPassportStatus["polling_status"]>>([
  "idle", "queued", "running", "retrying", "completed", "failed", "canceled", "timed_out", "not_authorized", "unavailable", "unknown"
]);
const UPLOAD_STATES = new Set(["pending", "pending_upload", "uploaded", "completed", "failed", "unknown"]);

export function projectFounderScan(value: unknown): FounderScanView | null {
  const record = asRecord(value);
  const artifactId = record?.artifact_id;
  if (typeof artifactId !== "string" || !artifactId) {
    return null;
  }
  return {
    artifact_id: artifactId,
    status: normalizeState(record.status ?? record.state, SCAN_STATES) as FounderScanState
  };
}

export function projectFounderUpload(value: unknown): { status: FounderScanState } {
  const record = asRecord(value);
  const status = record?.status ?? record?.state;
  return { status: normalizeState(status, UPLOAD_STATES) as FounderScanState };
}

export function projectFounderUploadPreview(value: unknown, artifactId: string): FounderUploadPreview | null {
  const record = asRecord(value);
  if (!record || !artifactId) {
    return null;
  }
  return {
    artifact_id: artifactId,
    file_count: nonNegativeInteger(record.file_count),
    dependency_count: nonNegativeInteger(record.dependency_count),
    finding_count: nonNegativeInteger(record.finding_count),
    env_key_names: stringList(record.env_key_names)
  };
}

export function projectLaunchPassportStatus(value: unknown): LaunchPassportStatus {
  const record = asRecord(value);
  const projectId = safeIdentifier(record?.lp_project_id);
  const capabilities = asRecord(record?.capabilities);
  const pollingStatus = typeof record?.polling_status === "string" && POLLING_STATES.has(record.polling_status as NonNullable<LaunchPassportStatus["polling_status"]>)
    ? record.polling_status as NonNullable<LaunchPassportStatus["polling_status"]>
    : undefined;
  const attempts = nonNegativeInteger(record?.attempts);
  return {
    status: normalizeState(record?.status ?? record?.state, CONNECTION_STATES, "unknown") as LaunchPassportStatus["status"],
    token_configured: record?.token_configured === true,
    ...(projectId ? { lp_project_id: projectId } : {}),
    capabilities: { launch_scan: capabilities?.launch_scan === true },
    ...(pollingStatus ? { polling_status: pollingStatus } : {}),
    ...(typeof record?.polling === "string" && (record.polling === "scheduler_enabled" || record.polling === "scheduler_disabled")
      ? { polling: record.polling }
      : {}),
    ...(typeof record?.last_polled_at === "string" ? { last_polled_at: record.last_polled_at } : {}),
    ...(typeof record?.next_attempt_at === "string" ? { next_attempt_at: record.next_attempt_at } : {}),
    ...(attempts !== undefined ? { attempts } : {}),
    ...(typeof record?.polling_error === "string" ? { polling_error: record.polling_error || null } : {})
  };
}

export function projectFounderResults(value: unknown): FounderResults {
  const record = asRecord(value);
  const rawScans = record?.scans;
  let scanRecords: unknown[] = [];
  if (Array.isArray(rawScans)) {
    scanRecords = rawScans;
  } else {
    const scanRecord = asRecord(rawScans);
    if (Array.isArray(scanRecord?.items)) {
      scanRecords = scanRecord.items;
    }
  }
  const scanRecord = asRecord(rawScans);
  const rawCount = scanRecord?.count;
  const count = scanRecords.length > 0
    ? scanRecords.length
    : nonNegativeInteger(rawCount) ?? 0;
  const latestReport = record?.latest_report;
  return {
    ...(safeIdentifier(record?.project_id) ? { project_id: safeIdentifier(record?.project_id) } : {}),
    scans: {
      count,
      states: scanRecords.map((item): FounderScanState => {
        const scan = asRecord(item);
        return normalizeState(scan?.status ?? scan?.state, SCAN_STATES) as FounderScanState;
      })
    },
    latest_report: { available: hasContent(latestReport) }
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function normalizeState(value: unknown, allowed: Set<string>, fallback = "unknown"): string {
  return typeof value === "string" && allowed.has(value) ? value : fallback;
}

function nonNegativeInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && !looksSecretLike(item)) : [];
}

function safeIdentifier(value: unknown): string | undefined {
  return typeof value === "string" && value && !looksSecretLike(value) ? value : undefined;
}

function looksSecretLike(value: string): boolean {
  return /(?:bearer|token|secret|password|api[_-]?key)/i.test(value)
    || /(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|(?:sk|rk)_(?:live|test)_[0-9A-Za-z_]+|(?:gh[pousr]|github_pat)_[0-9A-Za-z_]+|xox[baprs]-[0-9A-Za-z-]+)/.test(value);
}

function hasContent(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === "") {
    return false;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}
