import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import type {
  MicrosoftAdminEvidencePage,
  MicrosoftAdminRemediation,
  MicrosoftAdminRunbookPlan
} from "../api/types";
import { useDashboard } from "../app/DashboardContext";
import { PaginatedEvidenceTable, type EvidenceColumn } from "../components/PaginatedEvidenceTable";
import { RoleGate } from "../components/RoleGate";

type MicrosoftAdminSummary = {
  non_operational_services: number;
  open_service_issues: number;
  secure_score_percent: number | null;
  failed_sign_ins: number;
  risky_sign_ins: number;
  risky_users: number;
  conditional_access_policies: number;
  conditional_access_disabled: number;
  conditional_access_report_only: number;
  managed_devices: number;
  noncompliant_devices: number;
  unencrypted_devices: number;
  stale_devices: number;
  intune_apps: number;
  compliance_policies: number;
  autopilot_devices: number;
  active_defender_incidents: number;
  high_severity_incidents: number;
  active_defender_alerts: number;
};

type MicrosoftAdminRecommendation = {
  priority: string;
  code: string;
  summary: string;
  automatic_execution: boolean;
};

type MicrosoftAdminDashboard = {
  generated_at: string;
  status: string;
  summary: MicrosoftAdminSummary;
  recommendations: MicrosoftAdminRecommendation[];
  source_statuses: Record<string, string>;
};

type MicrosoftAdminFinding = {
  code: string;
  severity: string;
  summary: string;
  evidence: Record<string, unknown>;
  recommended_action: string;
  action_id: string | null;
  approval_required: boolean;
};

type MicrosoftAdminDiagnostic = {
  user_identity: string;
  device_name: string;
  generated_at: string;
  evidence_completeness: number;
  probable_root_cause: string;
  findings: MicrosoftAdminFinding[];
  source_statuses: Record<string, string>;
};

type RunbookParameter = {
  name: string;
  kind: "boolean" | "integer" | "choice";
  description: string;
  default: boolean | number | string;
  minimum: number | null;
  maximum: number | null;
  choices: string[];
};

type MicrosoftAdminRunbook = {
  runbook_id: string;
  version: string;
  title: string;
  description: string;
  effect: "read" | "write";
  risk_level: number;
  timeout_seconds: number;
  approval_required: boolean;
  script_sha256: string;
  parameters: RunbookParameter[];
};

type RunbookRuntimeStatus = {
  status: "ready" | "blocked" | "not_configured";
  message: string;
  executable: string;
};

type RunbookDraftResponse = {
  approval: {
    id: number | string;
    action_type: string;
    status: string;
  };
  plan: {
    plan_digest: string;
    runbook_id: string;
  };
};

type EvidenceRow = Record<string, unknown>;
type EvidenceSurfaceKey =
  | "risky-users"
  | "sign-ins"
  | "conditional-access"
  | "defender-incidents"
  | "defender-alerts"
  | "secure-score"
  | "intune-apps"
  | "compliance-policies"
  | "autopilot"
  | "service-health"
  | "service-issues";

type EvidenceSurface = {
  key: EvidenceSurfaceKey;
  title: string;
  description: string;
  path: string;
  pageSize?: number | null;
  columns: EvidenceColumn<EvidenceRow>[];
};

type Notice = { kind: "success" | "danger"; message: string } | null;
type ParameterValue = boolean | number | string;

const metricDefinitions: Array<{
  label: string;
  value: (summary: MicrosoftAdminSummary) => string | number;
  detail: (summary: MicrosoftAdminSummary) => string;
  surface: EvidenceSurfaceKey;
}> = [
  {
    label: "Risky users",
    value: (summary) => summary.risky_users,
    detail: () => "Review users with identity risk",
    surface: "risky-users"
  },
  {
    label: "Sign-ins",
    value: (summary) => summary.risky_sign_ins,
    detail: (summary) => `${summary.failed_sign_ins} recent failed sign-ins`,
    surface: "sign-ins"
  },
  {
    label: "Conditional Access",
    value: (summary) => summary.conditional_access_policies,
    detail: (summary) => `${summary.conditional_access_disabled} disabled · ${summary.conditional_access_report_only} report-only`,
    surface: "conditional-access"
  },
  {
    label: "Defender incidents",
    value: (summary) => summary.active_defender_incidents,
    detail: (summary) => `${summary.high_severity_incidents} high severity`,
    surface: "defender-incidents"
  },
  {
    label: "Defender alerts",
    value: (summary) => summary.active_defender_alerts,
    detail: () => "Review active security detections",
    surface: "defender-alerts"
  },
  {
    label: "Secure Score",
    value: (summary) => summary.secure_score_percent === null ? "Unavailable" : `${summary.secure_score_percent}%`,
    detail: () => "Posture context, not compliance evidence",
    surface: "secure-score"
  },
  {
    label: "Intune apps",
    value: (summary) => summary.intune_apps,
    detail: () => "Review published application inventory",
    surface: "intune-apps"
  },
  {
    label: "Compliance policies",
    value: (summary) => summary.compliance_policies,
    detail: () => "Review endpoint compliance configuration",
    surface: "compliance-policies"
  },
  {
    label: "Autopilot devices",
    value: (summary) => summary.autopilot_devices,
    detail: () => "Review enrollment identities",
    surface: "autopilot"
  },
  {
    label: "Service health",
    value: (summary) => summary.non_operational_services,
    detail: () => "Non-operational Microsoft services",
    surface: "service-health"
  },
  {
    label: "Service issues",
    value: (summary) => summary.open_service_issues,
    detail: () => "Open Microsoft service issues",
    surface: "service-issues"
  }
];

const evidenceSurfaces: EvidenceSurface[] = [
  {
    key: "risky-users",
    title: "Risky users",
    description: "Identity protection users returned by the current tenant scope.",
    path: "/packs/microsoft-admin/identity/risky-users",
    columns: [
      { key: "user", label: "User", render: (row) => <strong>{textValue(row, "user_display_name") || textValue(row, "user_principal_name")}</strong> },
      { key: "risk_level", label: "Risk level", render: (row) => humanize(textValue(row, "risk_level")) },
      { key: "risk_state", label: "State", render: (row) => humanize(textValue(row, "risk_state")) },
      { key: "updated", label: "Last updated", render: (row) => formatDate(textValue(row, "risk_last_updated_date_time")) }
    ]
  },
  {
    key: "sign-ins",
    title: "Sign-ins",
    description: "Recent Entra sign-in evidence, including failure and device context.",
    path: "/packs/microsoft-admin/identity/sign-ins",
    columns: [
      { key: "user", label: "User", render: (row) => <strong>{textValue(row, "user_display_name") || textValue(row, "user_principal_name")}</strong> },
      { key: "created", label: "Time", render: (row) => formatDate(textValue(row, "created_date_time")) },
      { key: "application", label: "Application" },
      { key: "result", label: "Result", render: (row) => numberValue(row, "error_code") ? "Failed" : "Succeeded" },
      { key: "risk", label: "Risk", render: (row) => humanize(textValue(row, "risk_level")) }
    ]
  },
  {
    key: "conditional-access",
    title: "Conditional Access policies",
    description: "Configured policy states and bounded condition summaries.",
    path: "/packs/microsoft-admin/identity/conditional-access",
    columns: [
      { key: "display_name", label: "Policy" },
      { key: "state", label: "State", render: (row) => humanize(textValue(row, "state")) },
      { key: "conditions", label: "Conditions", render: (row) => conditionSummary(row) },
      { key: "controls", label: "Grant controls", render: (row) => nestedStrings(row, "grant_controls", "built_in_controls") }
    ]
  },
  {
    key: "defender-incidents",
    title: "Defender incidents",
    description: "Active and historical incidents returned by Microsoft Defender.",
    path: "/packs/microsoft-admin/security/incidents",
    columns: [
      { key: "display_name", label: "Incident" },
      { key: "severity", label: "Severity", render: (row) => humanize(textValue(row, "severity")) },
      { key: "status", label: "Status", render: (row) => humanize(textValue(row, "status")) },
      { key: "assigned_to", label: "Assigned to" },
      { key: "created", label: "Created", render: (row) => formatDate(textValue(row, "created_date_time")) }
    ]
  },
  {
    key: "defender-alerts",
    title: "Defender alerts",
    description: "Security detections and their current status from Microsoft Defender.",
    path: "/packs/microsoft-admin/security/alerts",
    columns: [
      { key: "title", label: "Alert" },
      { key: "severity", label: "Severity", render: (row) => humanize(textValue(row, "severity")) },
      { key: "status", label: "Status", render: (row) => humanize(textValue(row, "status")) },
      { key: "source", label: "Source", render: (row) => textValue(row, "service_source") || textValue(row, "detection_source") },
      { key: "created", label: "Created", render: (row) => formatDate(textValue(row, "created_date_time")) }
    ]
  },
  {
    key: "secure-score",
    title: "Secure Score",
    description: "The latest score record and its tenant comparison context.",
    path: "/packs/microsoft-admin/security/secure-score",
    pageSize: null,
    columns: [
      { key: "created", label: "As of", render: (row) => formatDate(textValue(row, "created_date_time")) },
      { key: "score", label: "Current / maximum", render: (row) => `${displayValue(row["current_score"])} / ${displayValue(row["max_score"])}` },
      { key: "users", label: "Active / licensed", render: (row) => `${displayValue(row["active_user_count"])} / ${displayValue(row["licensed_user_count"])}` },
      { key: "services", label: "Enabled services", render: (row) => arrayValue(row, "enabled_services") }
    ]
  },
  {
    key: "intune-apps",
    title: "Intune apps",
    description: "Published application inventory returned by Intune.",
    path: "/packs/microsoft-admin/endpoint/apps",
    columns: [
      { key: "display_name", label: "Application" },
      { key: "publisher", label: "Publisher" },
      { key: "developer", label: "Developer" },
      { key: "modified", label: "Last modified", render: (row) => formatDate(textValue(row, "last_modified_date_time")) }
    ]
  },
  {
    key: "compliance-policies",
    title: "Compliance policies",
    description: "Endpoint compliance policy definitions returned by Intune.",
    path: "/packs/microsoft-admin/endpoint/compliance-policies",
    columns: [
      { key: "display_name", label: "Policy" },
      { key: "version", label: "Version" },
      { key: "modified", label: "Last modified", render: (row) => formatDate(textValue(row, "last_modified_date_time")) },
      { key: "description", label: "Description" }
    ]
  },
  {
    key: "autopilot",
    title: "Autopilot devices",
    description: "Windows Autopilot device identities and enrollment state.",
    path: "/packs/microsoft-admin/endpoint/autopilot",
    columns: [
      { key: "display_name", label: "Device" },
      { key: "hardware", label: "Hardware", render: (row) => [textValue(row, "manufacturer"), textValue(row, "model")].filter(Boolean).join(" ") },
      { key: "enrollment_state", label: "Enrollment", render: (row) => humanize(textValue(row, "enrollment_state")) },
      { key: "group_tag", label: "Group tag" },
      { key: "last_contacted", label: "Last contacted", render: (row) => formatDate(textValue(row, "last_contacted_date_time")) }
    ]
  },
  {
    key: "service-health",
    title: "Service health",
    description: "Microsoft service health statuses for the current tenant.",
    path: "/packs/microsoft-admin/service-health",
    columns: [
      { key: "service", label: "Service" },
      { key: "status", label: "Status", render: (row) => humanize(textValue(row, "status")) },
      { key: "id", label: "Record" }
    ]
  },
  {
    key: "service-issues",
    title: "Service issues",
    description: "Microsoft service incidents and their latest known impact.",
    path: "/packs/microsoft-admin/service-issues",
    columns: [
      { key: "title", label: "Issue" },
      { key: "service", label: "Service" },
      { key: "status", label: "Status", render: (row) => humanize(textValue(row, "status")) },
      { key: "impact", label: "Impact", render: (row) => textValue(row, "impact_description") },
      { key: "modified", label: "Last modified", render: (row) => formatDate(textValue(row, "last_modified_date_time")) }
    ]
  }
];

export function MicrosoftAdmin() {
  const { role, roleResolved, selectedClientId } = useDashboard();
  const [dashboard, setDashboard] = useState<MicrosoftAdminDashboard | null>(null);
  const [remediations, setRemediations] = useState<MicrosoftAdminRemediation[]>([]);
  const [remediationError, setRemediationError] = useState("");
  const [runbooks, setRunbooks] = useState<MicrosoftAdminRunbook[]>([]);
  const [runtime, setRuntime] = useState<RunbookRuntimeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [userIdentity, setUserIdentity] = useState("");
  const [deviceName, setDeviceName] = useState("");
  const [diagnostic, setDiagnostic] = useState<MicrosoftAdminDiagnostic | null>(null);
  const [diagnosticBusy, setDiagnosticBusy] = useState(false);
  const [diagnosticError, setDiagnosticError] = useState("");
  const [selectedRunbookId, setSelectedRunbookId] = useState("");
  const [runbookParameters, setRunbookParameters] = useState<Record<string, ParameterValue>>({});
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftNotice, setDraftNotice] = useState<Notice>(null);
  const [runbookPlan, setRunbookPlan] = useState<MicrosoftAdminRunbookPlan | null>(null);
  const [selectedSurfaceKey, setSelectedSurfaceKey] = useState<EvidenceSurfaceKey | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    const results = await Promise.allSettled([
      apiFetch<MicrosoftAdminDashboard>("/packs/microsoft-admin/dashboard"),
      apiFetch<MicrosoftAdminRunbook[]>("/packs/microsoft-admin/runbooks"),
      apiFetch<RunbookRuntimeStatus>("/packs/microsoft-admin/runbooks/status"),
      apiFetch<MicrosoftAdminRemediation[]>("/packs/microsoft-admin/remediations")
    ]);
    const failures: string[] = [];
    if (results[0].status === "fulfilled") {
      setDashboard(results[0].value);
    } else {
      failures.push(friendlyError(results[0].reason, "Microsoft posture is unavailable."));
    }
    if (results[1].status === "fulfilled") {
      setRunbooks(results[1].value);
    } else {
      failures.push(friendlyError(results[1].reason, "The PowerShell runbook catalog is unavailable."));
    }
    if (results[2].status === "fulfilled") {
      setRuntime(results[2].value);
    } else {
      failures.push(friendlyError(results[2].reason, "PowerShell runtime status is unavailable."));
    }
    if (results[3].status === "fulfilled") {
      setRemediations(results[3].value);
      setRemediationError("");
    } else {
      const message = friendlyError(results[3].reason, "The remediation catalog is unavailable.");
      setRemediationError(message);
      failures.push(message);
    }
    setLoadError(failures.join(" "));
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedRunbook = useMemo(
    () => runbooks.find((runbook) => runbook.runbook_id === selectedRunbookId) ?? runbooks[0] ?? null,
    [runbooks, selectedRunbookId]
  );

  const selectedSurface = useMemo(
    () => evidenceSurfaces.find((surface) => surface.key === selectedSurfaceKey) ?? null,
    [selectedSurfaceKey]
  );

  const loadEvidencePage = useCallback(
    (path: string, cursor: string | null, pageSize: number | null = 25) => {
      const query = new URLSearchParams();
      if (pageSize !== null) query.set("page_size", String(pageSize));
      if (cursor) query.set("cursor", cursor);
      const queryString = query.toString();
      return apiFetch<MicrosoftAdminEvidencePage<EvidenceRow>>(queryString ? `${path}?${queryString}` : path);
    },
  []);

  const selectedSurfaceLoader = useMemo(
    () => selectedSurface ? (cursor: string | null) => loadEvidencePage(
      selectedSurface.path,
      cursor,
      selectedSurface.pageSize === undefined ? 25 : selectedSurface.pageSize
    ) : null,
    [loadEvidencePage, selectedSurface]
  );

  useEffect(() => {
    if (runbookPlan && runbookPlan.client_id !== selectedClientId) {
      setRunbookPlan(null);
    }
  }, [runbookPlan, selectedClientId]);

  useEffect(() => {
    if (!selectedRunbook) {
      setSelectedRunbookId("");
      setRunbookParameters({});
      return;
    }
    setSelectedRunbookId(selectedRunbook.runbook_id);
    setRunbookParameters(parameterDefaults(selectedRunbook));
    setRunbookPlan(null);
    setDraftNotice(null);
  }, [selectedRunbook?.runbook_id]);

  async function submitDiagnostic(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (userIdentity.trim().length < 3) return;
    setDiagnosticBusy(true);
    setDiagnosticError("");
    try {
      const result = await apiFetch<MicrosoftAdminDiagnostic>(
        "/packs/microsoft-admin/diagnostics/access",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_identity: userIdentity.trim(),
            device_name: deviceName.trim() || null
          })
        }
      );
      setDiagnostic(result);
    } catch (error) {
      setDiagnosticError(friendlyError(error, "Access diagnosis failed."));
    } finally {
      setDiagnosticBusy(false);
    }
  }

  async function submitRunbookDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRunbook || !selectedClientId) return;
    setDraftBusy(true);
    setDraftNotice(null);
    try {
      if (!runbookPlan) {
        const plan = await apiFetch<MicrosoftAdminRunbookPlan>(
          "/packs/microsoft-admin/runbooks/plan",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              runbook_id: selectedRunbook.runbook_id,
              parameters: runbookParameters,
              client_id: selectedClientId
            })
          }
        );
        setRunbookPlan(plan);
        return;
      }
      const response = await apiFetch<RunbookDraftResponse>(
        "/packs/microsoft-admin/runbooks/drafts",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            runbook_id: selectedRunbook.runbook_id,
            parameters: runbookParameters,
            client_id: selectedClientId
          })
        }
      );
      setDraftNotice({
        kind: "success",
        message: `Draft created as approval #${response.approval.id}. No PowerShell has executed.`
      });
    } catch (error) {
      setDraftNotice({ kind: "danger", message: friendlyError(error, "Runbook draft creation failed.") });
    } finally {
      setDraftBusy(false);
    }
  }

  function selectRunbook(runbookId: string) {
    const runbook = runbooks.find((item) => item.runbook_id === runbookId);
    setSelectedRunbookId(runbookId);
    setRunbookParameters(runbook ? parameterDefaults(runbook) : {});
    setRunbookPlan(null);
    setDraftNotice(null);
  }

  function changeRunbookParameter(name: string, value: ParameterValue) {
    setRunbookPlan(null);
    setDraftNotice(null);
    setRunbookParameters((current) => ({ ...current, [name]: value }));
  }

  return (
    <div className="screen-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Microsoft cloud & endpoint</p>
            <h2>Microsoft Administrator</h2>
            <p className="screen-note">
              Correlate Microsoft 365, Entra, Intune, Defender, and local Windows evidence before creating a governed action.
            </p>
          </div>
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        {dashboard ? (
          <p className="screen-note">
            Evidence status: <strong>{humanize(dashboard.status)}</strong> · generated {formatDate(dashboard.generated_at)}
          </p>
        ) : null}
      </section>

      {loadError ? <div className="notice danger" role="alert">{loadError}</div> : null}
      {loading && !dashboard ? <section className="panel"><p>Loading Microsoft evidence…</p></section> : null}

      {dashboard ? (
        <>
          <section className="overview-cards" aria-label="Microsoft administration posture">
            {metricDefinitions.map((metric) => (
              <button
                className={`overview-card microsoft-evidence-card${selectedSurfaceKey === metric.surface ? " selected" : ""}`}
                key={metric.label}
                type="button"
                aria-expanded={selectedSurfaceKey === metric.surface}
                onClick={() => setSelectedSurfaceKey(metric.surface)}
              >
                <span>{metric.label}</span>
                <strong>{metric.value(dashboard.summary)}</strong>
                <small>{metric.detail(dashboard.summary)}</small>
                <em>Open evidence</em>
              </button>
            ))}
          </section>

          {selectedSurface && selectedSurfaceLoader ? (
            <PaginatedEvidenceTable
              key={selectedSurface.key}
              title={selectedSurface.title}
              description={selectedSurface.description}
              columns={selectedSurface.columns}
              loadPage={selectedSurfaceLoader}
              onClose={() => setSelectedSurfaceKey(null)}
              rowKey={(row, index) => textValue(row, "id") || `${selectedSurface.key}-${index}`}
            />
          ) : null}

          <section className="panel" aria-labelledby="microsoft-recommendations-heading">
            <div className="panel-heading">
              <div>
                <h3 id="microsoft-recommendations-heading">Evidence-derived recommendations</h3>
                <span>Recommendations do not execute automatically.</span>
              </div>
            </div>
            {dashboard.recommendations.length ? (
              <div className="event-list">
                {dashboard.recommendations.map((recommendation) => (
                  <article className="event-row" key={recommendation.code}>
                    <div>
                      <strong>{recommendation.summary}</strong>
                      <small>{recommendation.code}</small>
                    </div>
                    <span className="status-pill">{humanize(recommendation.priority)}</span>
                  </article>
                ))}
              </div>
            ) : <p className="screen-note">No recommendations were produced from the available evidence.</p>}
            <details>
              <summary>Source readiness</summary>
              <div className="event-list">
                {Object.entries(dashboard.source_statuses).map(([source, status]) => (
                  <div className="event-row" key={source}>
                    <span>{humanize(source)}</span>
                    <span className="status-pill">{humanize(status)}</span>
                  </div>
                ))}
              </div>
            </details>
          </section>

          <section className="panel" aria-labelledby="microsoft-remediations-heading">
            <div className="panel-heading">
              <div>
                <h3 id="microsoft-remediations-heading">Recommended remediations</h3>
                <span>Review the governed action catalog before creating any approval.</span>
              </div>
            </div>
            {remediationError ? <div className="notice danger" role="alert">{remediationError}</div> : null}
            {!remediationError && remediations.length === 0 ? (
              <p className="screen-note">No remediation actions are available for this pack.</p>
            ) : null}
            {remediations.length ? (
              <div className="event-list">
                {remediations.map((remediation) => (
                  <article className="event-row" key={remediation.action_id}>
                    <div>
                      <strong>{remediation.description}</strong>
                      <small><code>{remediation.action_id}</code> · Risk level {remediation.risk_level} · {remediation.approval_required ? "Approval required" : "No approval required"}</small>
                    </div>
                    <Link className="secondary-button" to={`/integrations/smart-actions#${encodeURIComponent(remediation.action_id)}`}>
                      Open action catalog entry
                    </Link>
                  </article>
                ))}
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      <section className="panel" aria-labelledby="access-diagnostic-heading">
        <div className="panel-heading">
          <div>
            <h3 id="access-diagnostic-heading">Access diagnostic</h3>
            <span>Correlate identity, licensing, sign-in, service, and endpoint evidence.</span>
          </div>
        </div>
        <form onSubmit={(event) => void submitDiagnostic(event)}>
          <label htmlFor="microsoft-admin-user">User principal name or immutable user ID</label>
          <input
            id="microsoft-admin-user"
            value={userIdentity}
            minLength={3}
            required
            disabled={diagnosticBusy}
            onChange={(event) => setUserIdentity(event.target.value)}
          />
          <label htmlFor="microsoft-admin-device">Optional Intune device name</label>
          <input
            id="microsoft-admin-device"
            value={deviceName}
            disabled={diagnosticBusy}
            onChange={(event) => setDeviceName(event.target.value)}
          />
          {diagnosticError ? <div className="notice danger" role="alert">{diagnosticError}</div> : null}
          <button type="submit" disabled={diagnosticBusy || userIdentity.trim().length < 3}>
            {diagnosticBusy ? "Diagnosing…" : "Run diagnostic"}
          </button>
        </form>

        {diagnostic ? (
          <div className="screen-stack" aria-live="polite">
            <div className="notice success" role="status">
              Evidence completeness: {Math.round(diagnostic.evidence_completeness * 100)}%
            </div>
            {diagnostic.probable_root_cause ? (
              <div className="notice danger">
                <strong>Probable root cause:</strong> {diagnostic.probable_root_cause}
              </div>
            ) : null}
            <div className="event-list">
              {diagnostic.findings.map((finding) => (
                <article className="event-row" key={`${finding.code}-${finding.summary}`}>
                  <div>
                    <strong>{finding.summary}</strong>
                    <small>{finding.recommended_action}</small>
                    {finding.action_id ? (
                      <small>
                        Suggested governed action: <code>{finding.action_id}</code>
                        {finding.approval_required ? " · approval required" : ""}
                      </small>
                    ) : null}
                  </div>
                  <span className="status-pill">{humanize(finding.severity)}</span>
                </article>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      <RoleGate
        role={role}
        resolved={roleResolved}
        allowed={["technician", "admin"]}
        fallback={(
          <section className="panel">
            <h3>Technician access required</h3>
            <p className="screen-note">Runbook plans and approval drafts require technician or administrator access.</p>
          </section>
        )}
      >
        <section className="panel" aria-labelledby="powershell-runbooks-heading">
          <div className="panel-heading">
            <div>
              <h3 id="powershell-runbooks-heading">Governed PowerShell runbooks</h3>
              <span>Fixed scripts only. This workspace creates approval drafts; it does not execute PowerShell.</span>
            </div>
            {runtime ? <span className="status-pill">{humanize(runtime.status)}</span> : null}
          </div>
          {runtime ? <p className="screen-note">{runtime.message}</p> : null}
          {!selectedClientId ? (
            <div className="notice danger" role="alert">Select a client from the top bar before creating a runbook draft.</div>
          ) : null}
          {selectedRunbook ? (
            <form onSubmit={(event) => void submitRunbookDraft(event)}>
              <label htmlFor="microsoft-admin-runbook">Runbook</label>
              <select
                id="microsoft-admin-runbook"
                value={selectedRunbook.runbook_id}
                disabled={draftBusy}
                onChange={(event) => selectRunbook(event.target.value)}
              >
                {runbooks.map((runbook) => (
                  <option key={runbook.runbook_id} value={runbook.runbook_id}>{runbook.title}</option>
                ))}
              </select>
              <p className="screen-note">
                {selectedRunbook.description} Effect: {selectedRunbook.effect}. Risk level {selectedRunbook.risk_level}.
              </p>
              {selectedRunbook.parameters.map((parameter) => (
                <RunbookParameterField
                  key={parameter.name}
                  parameter={parameter}
                  value={runbookParameters[parameter.name] ?? parameter.default}
                  disabled={draftBusy}
                  onChange={(value) => changeRunbookParameter(parameter.name, value)}
                />
              ))}
              {runbookPlan ? (
                <section className="microsoft-runbook-plan" aria-labelledby="microsoft-runbook-plan-heading">
                  <div className="panel-heading">
                    <div>
                      <h4 id="microsoft-runbook-plan-heading">Runbook dry-run preview</h4>
                      <span>Review the server-validated plan before creating an approval draft.</span>
                    </div>
                    <span className="status-pill">Preview only</span>
                  </div>
                  <dl className="microsoft-runbook-plan-grid">
                    <div><dt>Runbook</dt><dd>{runbookPlan.title}</dd></div>
                    <div><dt>Tenant</dt><dd><code>{runbookPlan.client_id}</code></dd></div>
                    <div><dt>Effect</dt><dd>{humanize(runbookPlan.effect)}</dd></div>
                    <div><dt>Risk level</dt><dd>{runbookPlan.risk_level}</dd></div>
                    <div><dt>Approval</dt><dd>{runbookPlan.approval_required ? "Required" : "Not required"}</dd></div>
                    <div><dt>Plan digest</dt><dd><code>{runbookPlan.plan_digest}</code></dd></div>
                  </dl>
                  <details className="technical-details">
                    <summary>Show validated parameters</summary>
                    <pre>{formatJson(runbookPlan.parameters)}</pre>
                  </details>
                </section>
              ) : null}
              {draftNotice ? (
                draftNotice.kind === "success" ? (
                  <div className="notice success" role="status">
                    {draftNotice.message} <Link to="/approvals">Go to Approvals</Link>
                  </div>
                ) : <div className="notice danger" role="alert">{draftNotice.message}</div>
              ) : null}
              <button type="submit" disabled={draftBusy || !selectedClientId}>
                {draftBusy ? (runbookPlan ? "Creating draft…" : "Previewing plan…") : (runbookPlan ? "Confirm and create approval draft" : "Preview runbook plan")}
              </button>
              {runbookPlan ? (
                <button type="button" className="secondary-button" disabled={draftBusy} onClick={() => setRunbookPlan(null)}>
                  Change parameters
                </button>
              ) : null}
            </form>
          ) : <p className="screen-note">No fixed runbooks are available.</p>}
        </section>
      </RoleGate>
    </div>
  );
}

function RunbookParameterField({
  parameter,
  value,
  disabled,
  onChange
}: {
  parameter: RunbookParameter;
  value: ParameterValue;
  disabled: boolean;
  onChange: (value: ParameterValue) => void;
}) {
  const inputId = `runbook-${parameter.name}`;
  if (parameter.kind === "boolean") {
    return (
      <label htmlFor={inputId}>
        <input
          id={inputId}
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        {parameter.description}
      </label>
    );
  }
  if (parameter.kind === "choice") {
    return (
      <div>
        <label htmlFor={inputId}>{parameter.description}</label>
        <select
          id={inputId}
          value={String(value)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        >
          {parameter.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
        </select>
      </div>
    );
  }
  return (
    <div>
      <label htmlFor={inputId}>{parameter.description}</label>
      <input
        id={inputId}
        type="number"
        value={Number(value)}
        min={parameter.minimum ?? undefined}
        max={parameter.maximum ?? undefined}
        disabled={disabled}
        onChange={(event) => onChange(event.target.valueAsNumber)}
      />
    </div>
  );
}

function parameterDefaults(runbook: MicrosoftAdminRunbook): Record<string, ParameterValue> {
  return Object.fromEntries(runbook.parameters.map((parameter) => [parameter.name, parameter.default]));
}

function friendlyError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function textValue(row: EvidenceRow, key: string): string {
  const value = row[key];
  return typeof value === "string" ? value : "";
}

function numberValue(row: EvidenceRow, key: string): number {
  const value = row[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function arrayValue(row: EvidenceRow, key: string): string {
  const value = row[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").join(", ") || "None recorded" : "None recorded";
}

function nestedStrings(row: EvidenceRow, parentKey: string, childKey: string): string {
  const parent = row[parentKey];
  if (!parent || typeof parent !== "object" || Array.isArray(parent)) return "None recorded";
  return arrayValue(parent as EvidenceRow, childKey);
}

function conditionSummary(row: EvidenceRow): string {
  const conditions = row.conditions;
  if (!conditions || typeof conditions !== "object" || Array.isArray(conditions)) return "None recorded";
  const values = conditions as EvidenceRow;
  return `${numberValue(values, "included_users")} users · ${numberValue(values, "included_groups")} groups · ${numberValue(values, "included_applications")} apps`;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return formatJson(value);
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "Not recorded";
  } catch {
    return "Unable to render this value.";
  }
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "at an unknown time" : parsed.toLocaleString();
}
