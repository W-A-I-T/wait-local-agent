import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../../api/client";
import { FolderPicker } from "../../components/FolderPicker";
import { Wizard, type WizardStep } from "../../components/Wizard";

type FounderPreview = {
  artifact_id: string;
  schema_version?: string;
  project_name?: string;
  file_count?: number;
  manifest_count?: number;
  route_count?: number;
  env_key_names?: string[];
  finding_types?: string[];
};

type FounderLpStatus = {
  status?: string;
  base_url?: string;
  detail?: string;
};

export function FounderJourney() {
  const steps: WizardStep[] = [
    { id: "scan", title: "Scan founder project" },
    { id: "preflight", title: "Check preflight" },
    { id: "handoff", title: "Prepare handoff" },
    { id: "preview", title: "Review upload package" },
    { id: "upload", title: "Upload to Founder Pack" }
  ];

  const [step, setStep] = useState(0);
  const [scanPath, setScanPath] = useState("");
  const [artifactId, setArtifactId] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Founder journey is available to admins.");
  const [scan, setScan] = useState<Record<string, unknown> | null>(null);
  const [preflight, setPreflight] = useState<Record<string, unknown> | null>(null);
  const [handoff, setHandoff] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<FounderPreview | null>(null);
  const [lpStatus, setLpStatus] = useState<FounderLpStatus | null>(null);
  const [missingPack, setMissingPack] = useState(false);

  const reset = useCallback(() => {
    setScan(null);
    setPreflight(null);
    setHandoff(null);
    setPreview(null);
    setLpStatus(null);
  }, []);

  function isFounderUnavailable(error: unknown): boolean {
    return typeof error === "string"
      ? /HTTP 501/.test(error)
      : error instanceof Error
        ? /HTTP 501/.test(error.message)
        : false;
  }

  async function loadScan(path = scanPath): Promise<boolean> {
    if (!path) {
      setStatusMessage("Choose a path before scanning.");
      return false;
    }
    try {
      setIsBusy(true);
      const body = await apiFetch<Record<string, unknown>>("/founder/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path })
      });
      setScan(body);
      setMissingPack(false);
      const nextArtifactId = String(body.artifact_id || "art-1");
      setArtifactId(nextArtifactId);
      setStatusMessage(`Scan complete. Artifact ${nextArtifactId} detected.`);
      return true;
    } catch (error) {
      if (isFounderUnavailable(error)) {
        setMissingPack(true);
        setStatusMessage("Install the Founder Pack from Settings to enable this journey.");
        return false;
      }
      setStatusMessage(error instanceof Error ? error.message : "Scan failed.");
      return false;
    } finally {
      setIsBusy(false);
    }
  }

  async function loadPreflight(): Promise<boolean> {
    try {
      setIsBusy(true);
      const body = await apiFetch<Record<string, unknown>>("/founder/preflight/latest");
      setPreflight(body);
      setMissingPack(false);
      setStatusMessage(`Preflight status: ${String(body.status || "ready")}.`);
      return true;
    } catch (error) {
      if (isFounderUnavailable(error)) {
        setMissingPack(true);
      }
      setStatusMessage(error instanceof Error ? error.message : "Preflight not ready.");
      return false;
    } finally {
      setIsBusy(false);
    }
  }

  async function loadHandoff(): Promise<boolean> {
    try {
      setIsBusy(true);
      const body = await apiFetch<Record<string, unknown>>("/founder/vault");
      setHandoff(body);
      setMissingPack(false);
      setStatusMessage("Handoff draft loaded. Continue to preview the artifact bundle.");
      return true;
    } catch (error) {
      if (isFounderUnavailable(error)) {
        setMissingPack(true);
      }
      setStatusMessage(error instanceof Error ? error.message : "Handoff load failed.");
      return false;
    } finally {
      setIsBusy(false);
    }
  }

  async function loadPreview(): Promise<boolean> {
    if (!artifactId) {
      setStatusMessage("Set an artifact id before preview.");
      return false;
    }
    try {
      setIsBusy(true);
      const body = await apiFetch<FounderPreview>(`/founder/upload-preview/${encodeURIComponent(artifactId)}`);
      setPreview(body);
      setMissingPack(false);
      setStatusMessage(`Preview loaded with ${body.file_count || 0} file(s).`);
      return true;
    } catch (error) {
      if (isFounderUnavailable(error)) {
        setMissingPack(true);
      }
      setStatusMessage(error instanceof Error ? error.message : "Preview not available.");
      return false;
    } finally {
      setIsBusy(false);
    }
  }

  async function submitUpload(): Promise<void> {
    if (!artifactId) {
      setStatusMessage("Set an artifact id before upload.");
      return;
    }
    try {
      setIsBusy(true);
      await apiFetch<Record<string, unknown>>(`/founder/upload/${encodeURIComponent(artifactId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true })
      });
      const status = await apiFetch<FounderLpStatus>("/founder/lp-status");
      setLpStatus(status);
      setMissingPack(false);
      setStatusMessage(`Upload accepted: ${status.status || "done"}.`);
    } catch (error) {
      if (isFounderUnavailable(error)) {
        setMissingPack(true);
      }
      setStatusMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleNext() {
    if (step === 0 && await loadScan()) {
      setStep(1);
      return;
    }
    if (step === 1 && await loadPreflight()) {
      setStep(2);
      return;
    }
    if (step === 2 && await loadHandoff()) {
      setStep(3);
      return;
    }
    if (step === 3 && await loadPreview()) {
      setStep(4);
    }
  }

  return (
    <section className="founder-screen">
      {missingPack ? (
        <div className="notice danger">
          Founder Pack is not installed. Install it first on the <Link to="/settings">Settings / Packs</Link> screen.
        </div>
      ) : null}

      <Wizard
        activeStep={step}
        canContinue={true}
        canSubmit={step === 4 && Boolean(artifactId) && !isBusy}
        isBusy={isBusy}
        onBack={() => {
          reset();
          setStep((current) => Math.max(0, current - 1));
        }}
        onNext={() => void handleNext()}
        onSubmit={() => void submitUpload()}
        onClose={() => {
          setStep(0);
          reset();
        }}
        steps={steps}
      >
        {step === 0 ? (
          <div className="grid">
            <FolderPicker
              label="Project path"
              value={scanPath}
              onChange={setScanPath}
              placeholder="/path/to/launcher-project"
            />
            <button type="button" className="icon-button" onClick={() => void loadScan()}>
              Scan now
            </button>
            <pre className="code-panel">{scan ? JSON.stringify(scan, null, 2) : "No scan yet."}</pre>
          </div>
        ) : null}

        {step === 1 ? (
          <div className="grid">
            <button type="button" className="icon-button" onClick={() => void loadPreflight()}>
              Refresh preflight
            </button>
            <pre className="code-panel">{preflight ? JSON.stringify(preflight, null, 2) : "No preflight yet."}</pre>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="grid">
            <button type="button" className="icon-button" onClick={() => void loadHandoff()}>
              Load handoff draft
            </button>
            <pre className="code-panel">{handoff ? JSON.stringify(handoff, null, 2) : "No handoff yet."}</pre>
          </div>
        ) : null}

        {step === 3 ? (
          <div className="grid">
            <label>
              Artifact id
              <input
                value={artifactId}
                onChange={(event) => setArtifactId(event.target.value)}
                placeholder="art-1"
              />
            </label>
            <button type="button" className="icon-button" onClick={() => void loadPreview()}>
              Generate upload preview
            </button>
            <pre className="code-panel">{preview ? JSON.stringify(preview, null, 2) : "No preview yet."}</pre>
          </div>
        ) : null}

        {step === 4 ? (
          <div className="draft-form">
            <label>
              Upload confirmation
              <span className="screen-note">This final step submits the selected artifact and validates LP connectivity.</span>
            </label>
            <button type="button" onClick={() => void submitUpload()} disabled={isBusy || !artifactId}>
              Upload artifact {artifactId}
            </button>
            {lpStatus ? <p className="screen-note">LP status: {lpStatus.status || "ready"}</p> : null}
            {lpStatus?.base_url ? <p>Base URL: {lpStatus.base_url}</p> : null}
            {lpStatus?.detail ? <p>{lpStatus.detail}</p> : null}
          </div>
        ) : null}
      </Wizard>
      <p className="screen-note">{statusMessage}</p>
    </section>
  );
}
