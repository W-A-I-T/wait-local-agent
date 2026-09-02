import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError, apiFetch } from "../../api/client";
import {
  projectFounderResults,
  projectFounderScan,
  projectFounderUpload,
  projectFounderUploadPreview,
  projectLaunchPassportStatus
} from "../../api/founder";
import type { FounderResults, FounderScanView, FounderUploadPreview, LaunchPassportStatus } from "../../api/types";
import { useDashboard } from "../../app/DashboardContext";
import { FolderPicker } from "../../components/FolderPicker";
import { RoleGate } from "../../components/RoleGate";
import { StatusChip } from "../../components/StatusChip";
import { Wizard, type WizardStep } from "../../components/Wizard";

const steps: WizardStep[] = [
  { id: "scan", title: "Scan your project" },
  { id: "preview", title: "Review what is shared" },
  { id: "upload", title: "Confirm upload" },
  { id: "launch", title: "Launch scan" },
  { id: "results", title: "View results" }
];

export function FounderJourney() {
  const { isAdmin, role } = useDashboard();
  const [step, setStep] = useState(0);
  const [scanPath, setScanPath] = useState("");
  const [artifactId, setArtifactId] = useState("");
  const [previewedArtifactId, setPreviewedArtifactId] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Choose a project folder to begin.");
  const [scan, setScan] = useState<FounderScanView | null>(null);
  const [preview, setPreview] = useState<FounderUploadPreview | null>(null);
  const [launchPassport, setLaunchPassport] = useState<LaunchPassportStatus | null>(null);
  const [results, setResults] = useState<FounderResults | null>(null);
  const [preflight, setPreflight] = useState<unknown>(null);
  const [vaultState, setVaultState] = useState<unknown>(null);
  const [launchResult, setLaunchResult] = useState<Record<string, unknown> | null>(null);
  const [confirmingLaunch, setConfirmingLaunch] = useState(false);
  const [connectionNotConfigured, setConnectionNotConfigured] = useState(false);
  const [missingPack, setMissingPack] = useState(false);
  const accessRole = role ?? (isAdmin ? "admin" : "viewer");

  const reset = useCallback(() => {
    setScan(null);
    setArtifactId("");
    setPreview(null);
    setPreviewedArtifactId("");
    setLaunchPassport(null);
    setResults(null);
    setPreflight(null);
    setVaultState(null);
    setLaunchResult(null);
    setConfirmingLaunch(false);
    setConnectionNotConfigured(false);
    setMissingPack(false);
  }, []);

  async function request<T>(path: string, init?: RequestInit): Promise<T | null> {
    try {
      return await apiFetch<T>(path, init);
    } catch (error) {
      handleFounderError(error);
      return null;
    }
  }

  function isFounderUnavailable(error: unknown): boolean {
    return error instanceof ApiRequestError && error.status === 501;
  }

  function handleFounderError(error: unknown) {
    const message = error instanceof Error
      ? `${error.message} ${error instanceof ApiRequestError ? error.technicalDetail : ""}`.toLowerCase()
      : "";
    if (isFounderUnavailable(error) || /http 501/.test(message)) {
      setMissingPack(true);
      setStatusMessage("This journey needs the Founder Pack. Install it from Settings, then return here.");
      return;
    }
    if (/not configured/.test(message)) {
      setConnectionNotConfigured(true);
      setStatusMessage("Launch Passport is not connected. This is optional; connect a project in Settings when the connection service is available.");
      return;
    }
    if (/insufficient_credits|402|credit/.test(message)) {
      setStatusMessage("Launch scan needs more Launch Passport credits. Add credits there, then try again.");
      setStep(3);
      return;
    }
    if (/rate_limited|429|rate limit/.test(message)) {
      setStatusMessage("Launch scan is temporarily rate limited. Wait a moment, then try again.");
      setStep(3);
      return;
    }
    if (/preview|required|stale/.test(message)) {
      setPreviewedArtifactId("");
      setStatusMessage("Review this upload package again, then confirm the upload. This keeps each upload tied to a fresh review.");
      setStep(1);
      return;
    }
    if (/project/.test(message)) {
      setStatusMessage("This scan belongs to a different project. Scan the project again after choosing the correct project connection.");
      setStep(0);
      return;
    }
    if (/http 401|http 403/.test(message)) {
      setStatusMessage("The project connection needs attention. Check it in Settings before trying again.");
      return;
    }
    setStatusMessage("That step could not finish. Check the project folder and try again.");
  }

  async function runScan(): Promise<boolean> {
    if (!scanPath) {
      setStatusMessage("Choose a project folder before scanning.");
      return false;
    }
    setIsBusy(true);
    try {
      const body = await request<unknown>("/founder/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: scanPath })
      });
      if (!body) {
        return false;
      }
      const projected = projectFounderScan(body);
      if (!projected) {
        setStatusMessage("The scan did not return a review package. Try again from the project folder.");
        return false;
      }
      const nextArtifactId = projected.artifact_id;
      setScan(projected);
      setArtifactId(nextArtifactId);
      setPreview(null);
      setPreviewedArtifactId("");
      setConnectionNotConfigured(false);
      setMissingPack(false);
      setStatusMessage("Scan complete. Review the upload package before anything leaves this appliance.");
      return true;
    } finally {
      setIsBusy(false);
    }
  }

  async function loadPreview(): Promise<boolean> {
    if (!artifactId) {
      setStatusMessage("Scan the project before reviewing an upload package.");
      return false;
    }
    setIsBusy(true);
    try {
      const body = await request<unknown>(`/founder/upload-preview/${encodeURIComponent(artifactId)}`);
      if (!body) {
        return false;
      }
      const projected = projectFounderUploadPreview(body, artifactId);
      if (!projected) {
        setStatusMessage("The review package was not returned in a usable form. Try scanning again.");
        return false;
      }
      setPreview(projected);
      setPreviewedArtifactId(artifactId);
      setConnectionNotConfigured(false);
      setMissingPack(false);
      setStatusMessage("Review complete. You can now confirm this exact upload package.");
      return true;
    } finally {
      setIsBusy(false);
    }
  }

  async function submitUpload(): Promise<void> {
    if (!artifactId || previewedArtifactId !== artifactId) {
      setStatusMessage("Review the current upload package before confirming it.");
      setStep(1);
      return;
    }
    setIsBusy(true);
    try {
      const uploadedBody = await request<unknown>(`/founder/upload/${encodeURIComponent(artifactId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true })
      });
      if (!uploadedBody) {
        return;
      }
      const uploaded = projectFounderUpload(uploadedBody);
      const [statusBody, resultsBody] = await Promise.all([
        request<unknown>("/founder/lp-status"),
        request<unknown>("/founder/results")
      ]);
      setLaunchPassport(projectLaunchPassportStatus(statusBody));
      setResults(projectFounderResults(resultsBody));
      setLaunchResult(null);
      setConnectionNotConfigured(false);
      setStatusMessage(`Upload ${uploadProgressLabel(uploaded.status)}. Your latest result is ready to review.`);
      setStep(3);
    } finally {
      setIsBusy(false);
    }
  }

  useEffect(() => {
    if (step !== 3) return;
    let cancelled = false;
    setIsBusy(true);
    void Promise.all([
      request<unknown>("/founder/preflight/latest"),
      request<unknown>("/founder/vault")
    ]).then(([latestPreflight, latestVault]) => {
      if (cancelled) return;
      setPreflight(latestPreflight);
      setVaultState(latestVault);
    }).finally(() => {
      if (!cancelled) setIsBusy(false);
    });
    return () => { cancelled = true; };
  }, [step]);

  async function launchScan(): Promise<void> {
    setConfirmingLaunch(false);
    setIsBusy(true);
    try {
      const body = await request<unknown>("/founder/launch-scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(artifactId ? { artifact_id: artifactId } : {})
      });
      if (!body || typeof body !== "object" || Array.isArray(body)) return;
      setLaunchResult(body as Record<string, unknown>);
      setStatusMessage("Launch scan request accepted. Continue to results when the latest state is ready.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleNext() {
    if (step === 0 && await runScan()) {
      setStep(1);
      return;
    }
    if (step === 1 && previewedArtifactId === artifactId) {
      setStep(2);
      return;
    }
    if (step === 2) {
      await submitUpload();
      return;
    }
    if (step === 3 && launchResult) {
      const [statusBody, resultsBody] = await Promise.all([
        request<unknown>("/founder/lp-status"),
        request<unknown>("/founder/results")
      ]);
      setLaunchPassport(projectLaunchPassportStatus(statusBody));
      setResults(projectFounderResults(resultsBody));
      setStep(4);
    }
  }

  return (
    <section className="founder-screen">
      <RoleGate
        role={accessRole}
        allowed={["admin"]}
        fallback={<div className="notice danger">Administrator access is required for the founder journey.</div>}
      >
        {missingPack ? (
          <div className="notice danger">
            The Founder Pack is not installed. Install it first on the <Link to="/settings">Settings / Packs</Link> screen.
          </div>
        ) : null}
        {connectionNotConfigured ? (
          <div className="notice">
            Launch Passport is not connected. The appliance remains fully usable without it. <Link to="/settings">View project connection settings</Link>.
          </div>
        ) : null}

        <Wizard
          activeStep={step}
          canContinue={!isBusy && (step !== 1 || previewedArtifactId === artifactId) && (step !== 2 || previewedArtifactId === artifactId) && (step !== 3 || launchResult !== null)}
          canSubmit={step === 4 && !isBusy}
          isBusy={isBusy}
          onBack={() => setStep((current) => Math.max(0, current - 1))}
          onNext={() => void handleNext()}
          onSubmit={() => {
            setStep(0);
            reset();
            setStatusMessage("Choose a project folder to begin.");
          }}
          onStepSelect={(index) => {
            if (index <= step) setStep(index);
          }}
          onClose={() => {
            setStep(0);
            reset();
            setStatusMessage("Choose a project folder to begin.");
          }}
          progressLabel={statusMessage}
          steps={steps}
          title="Prepare your Launch Passport upload"
          nextLabel={step === 1 ? "Continue to confirmation" : step === 2 ? "Upload reviewed package" : step === 3 ? "Continue to results" : "Next"}
          submitLabel="Finish"
        >
          {step === 0 ? (
            <div className="draft-form">
              <FolderPicker
                label="Project folder"
                value={scanPath}
                onChange={setScanPath}
                placeholder="/path/to/your-project"
              />
              <p className="screen-note">We prepare a review package on this appliance first. Nothing is sent during this scan.</p>
              {scan ? <p className="screen-note">A fresh scan is ready for review.</p> : null}
            </div>
          ) : null}

          {step === 1 ? (
            <div className="draft-form">
              <div className="privacy-promise">
                <h3>What will be shared</h3>
                <ul>
                  <li>Evidence about your project structure and dependencies.</li>
                  <li>Source files are not uploaded.</li>
                  <li>Environment values are excluded; configuration key names may be included.</li>
                  <li>Review the evidence summary before sending this package.</li>
                </ul>
              </div>
              {preview ? (
                <div className="founder-summary" aria-label="Upload package summary">
                  <div><strong>{preview.file_count ?? 0}</strong><span>files summarized</span></div>
                  <div><strong>{preview.dependency_count ?? 0}</strong><span>dependencies summarized</span></div>
                  <div><strong>{preview.finding_count ?? 0}</strong><span>findings included</span></div>
                </div>
              ) : <p className="screen-note">Generate the review package to see its evidence summary.</p>}
              {preview?.env_key_names?.length ? <p className="screen-note">Configuration key names included: {preview.env_key_names.join(", ")}.</p> : null}
              <button type="button" className="icon-button" onClick={() => void loadPreview()} disabled={isBusy || !artifactId}>
                {previewedArtifactId === artifactId ? "Refresh upload preview" : "Preview upload package"}
              </button>
              <details className="technical-details">
                <summary>Technical details</summary>
                <p>Artifact reference: {artifactId || "not created yet"}</p>
              </details>
            </div>
          ) : null}

          {step === 2 ? (
            <div className="draft-form">
              <h3>Confirm this upload</h3>
              <p>This sends only the package you just reviewed. Review is required again if you scan a different project.</p>
              <StatusChip status={previewedArtifactId === artifactId ? "completed" : "not_configured"} hint={previewedArtifactId === artifactId ? "This package was reviewed in this session." : "Review the package before uploading."} />
            </div>
          ) : null}

          {step === 3 ? (
            <div className="draft-form">
              <h3>Launch scan</h3>
              <p>Review the latest preflight and vault state before asking Launch Passport to start a scan.</p>
              <div className="smart-action-schema-grid">
                <section>
                  <h4>Latest preflight</h4>
                  {preflight === null ? <p className="screen-note">Preflight state is not available yet.</p> : <pre className="smart-action-code"><code>{JSON.stringify(safeFounderState(preflight), null, 2)}</code></pre>}
                </section>
                <section>
                  <h4>Vault state</h4>
                  {vaultState === null ? <p className="screen-note">Vault state is not available yet.</p> : <pre className="smart-action-code"><code>{JSON.stringify(safeFounderState(vaultState), null, 2)}</code></pre>}
                </section>
              </div>
              {launchResult ? <div className="connection-state" role="status"><strong>Launch result</strong><pre className="smart-action-code"><code>{JSON.stringify(launchResult, null, 2)}</code></pre></div> : null}
              {results ? (
                <section aria-labelledby="founder-current-results-heading">
                  <h3 id="founder-current-results-heading">Results</h3>
                  <StatusChip status={launchPassport?.status} />
                  {results.latest_report.available ? <p>Your latest report reference is available for this project.</p> : <p className="screen-note">No latest report reference was returned yet.</p>}
                  <p className="screen-note">{results.scans.count} scan record{results.scans.count === 1 ? "" : "s"} available.</p>
                </section>
              ) : null}
              {confirmingLaunch ? (
                <div className="notice confirm-panel" role="alertdialog" aria-label="Confirm launch scan">
                  <p>Run the Launch Passport scan for this reviewed project package?</p>
                  <div className="row-actions">
                    <button type="button" onClick={() => void launchScan()}>Yes, run launch scan</button>
                    <button type="button" className="icon-button" onClick={() => setConfirmingLaunch(false)}>Cancel</button>
                  </div>
                </div>
              ) : <button type="button" onClick={() => setConfirmingLaunch(true)} disabled={isBusy}>{isBusy ? "Checking…" : "Run launch scan"}</button>}
            </div>
          ) : null}

          {step === 4 ? (
            <div className="draft-form">
              <h3>Results</h3>
              <StatusChip status={launchPassport?.status} />
              {results?.latest_report.available ? <p>Your latest report reference is available for this project.</p> : <p className="screen-note">No latest report reference was returned yet.</p>}
              {results ? <p className="screen-note">{results.scans.count} scan record{results.scans.count === 1 ? "" : "s"} available.</p> : null}
              <details className="technical-details">
                <summary>Technical details</summary>
                <p>Project: {results?.project_id ?? launchPassport?.lp_project_id ?? "not returned"}</p>
              </details>
            </div>
          ) : null}
        </Wizard>
      </RoleGate>
    </section>
  );
}

export function uploadProgressLabel(status: string): string {
  if (status === "uploaded" || status === "completed") {
    return "complete";
  }
  if (status === "pending_upload") {
    return "accepted";
  }
  if (status === "failed") {
    return "not completed";
  }
  return "not completed";
}

function safeFounderState(value: unknown, key = ""): unknown {
  if (/token|secret|password|api[_-]?key|credential/i.test(key) && typeof value === "string") {
    return "[redacted]";
  }
  if (Array.isArray(value)) return value.map((item) => safeFounderState(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([entryKey, entryValue]) => [entryKey, safeFounderState(entryValue, entryKey)]));
  }
  return value;
}
