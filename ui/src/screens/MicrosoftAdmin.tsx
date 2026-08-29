import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
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

type Notice = { kind: "success" | "danger"; message: string } | null;
type ParameterValue = boolean | number | string;

const metricDefinitions: Array<{
  label: string;
  value: (summary: MicrosoftAdminSummary) => string | number;
  detail: (summary: MicrosoftAdminSummary) => string;
}> = [
  {
    label: "Microsoft services",
    value: (summary) => summary.non_operational_services,
    detail: (summary) => `${summary.open_service_issues} active service issues`
  },
  {
    label: "Secure Score",
    value: (summary) => summary.secure_score_percent === null ? "Unavailable" : `${summary.secure_score_percent}%`,
    detail: () => "Posture context, not compliance evidence"
  },
  {
    label: "Identity attention",
    value: (summary) => summary.risky_users + summary.risky_sign_ins,
    detail: (summary) => `${summary.failed_sign_ins} recent failed sign-ins`
  },
  {
    label: "Endpoint attention",
    value: (summary) => summary.noncompliant_devices,
    detail: (summary) => `${summary.unencrypted_devices} unencrypted · ${summary.stale_devices} stale`
  },
  {
    label: "Managed devices",
    value: (summary) => summary.managed_devices,
    detail: (summary) => `${summary.autopilot_devices} Autopilot identities`
  },
  {
    label: "Intune configuration",
    value: (summary) => summary.intune_apps,
    detail: (summary) => `${summary.compliance_policies} compliance policies`
  },
  {
    label: "Defender incidents",
    value: (summary) => summary.active_defender_incidents,
    detail: (summary) => `${summary.high_severity_incidents} high severity`
  },
  {
    label: "Defender alerts",
    value: (summary) => summary.active_defender_alerts,
    detail: (summary) => `${summary.conditional_access_policies} Conditional Access policies`
  }
];

export function MicrosoftAdmin() {
  const { role, roleResolved, selectedClientId } = useDashboard();
  const [dashboard, setDashboard] = useState<MicrosoftAdminDashboard | null>(null);
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

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    const results = await Promise.allSettled([
      apiFetch<MicrosoftAdminDashboard>("/packs/microsoft-admin/dashboard"),
      apiFetch<MicrosoftAdminRunbook[]>("/packs/microsoft-admin/runbooks"),
      apiFetch<RunbookRuntimeStatus>("/packs/microsoft-admin/runbooks/status")
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

  useEffect(() => {
    if (!selectedRunbook) {
      setSelectedRunbookId("");
      setRunbookParameters({});
      return;
    }
    setSelectedRunbookId(selectedRunbook.runbook_id);
    setRunbookParameters(parameterDefaults(selectedRunbook));
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
    setDraftNotice(null);
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
              <article className="overview-card" key={metric.label}>
                <span>{metric.label}</span>
                <strong>{metric.value(dashboard.summary)}</strong>
                <small>{metric.detail(dashboard.summary)}</small>
              </article>
            ))}
          </section>

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
                  onChange={(value) => setRunbookParameters((current) => ({ ...current, [parameter.name]: value }))}
                />
              ))}
              {draftNotice ? (
                draftNotice.kind === "success" ? (
                  <div className="notice success" role="status">
                    {draftNotice.message} <Link to="/approvals">Go to Approvals</Link>
                  </div>
                ) : <div className="notice danger" role="alert">{draftNotice.message}</div>
              ) : null}
              <button type="submit" disabled={draftBusy || !selectedClientId}>
                {draftBusy ? "Creating draft…" : "Create approval draft"}
              </button>
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

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "at an unknown time" : parsed.toLocaleString();
}
