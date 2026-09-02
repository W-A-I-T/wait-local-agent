import { useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../../api/client";
import { useDashboard } from "../../app/DashboardContext";
import type { TicketSummaryResponse } from "../../api/types";
import { Wizard, type WizardStep } from "../../components/Wizard";
import { FolderPicker } from "../../components/FolderPicker";

type OnboardingResult = {
  status?: string;
  message?: string;
  artifact_id?: string;
  summary?: string;
};

type OnboardingProps = {
  onDone: () => void;
  onDismiss: () => void;
  initialStep?: number;
};

const steps: WizardStep[] = [
  { id: "client", title: "Create a client", description: "Create the workspace that owns your operational data." },
  { id: "connector", title: "Connect a system", description: "Configure a connector instance in the administrator screen." },
  { id: "mapping", title: "Verify the client mapping", description: "Map an external company and verify its ownership." },
  { id: "knowledge", title: "Add knowledge (optional)" },
  { id: "demo", title: "Try a fixture ticket (optional)" }
];

export function OnboardingWizard({ onDone, onDismiss, initialStep = 0 }: OnboardingProps) {
  const { refresh, refreshConfiguration = refresh, isAdmin } = useDashboard();
  const [step, setStep] = useState(() => Math.min(Math.max(initialStep, 0), steps.length - 1));
  const [isBusy, setIsBusy] = useState(false);
  const [knowledgePath, setKnowledgePath] = useState("");
  const [ticketId, setTicketId] = useState("TCK-1001");
  const [resultMessage, setResultMessage] = useState("Welcome — complete each setup step to unlock full operations.");
  const [result, setResult] = useState<OnboardingResult>({});

  async function runIngest(): Promise<boolean> {
    if (!knowledgePath) {
      setResultMessage("Set a knowledge folder path to proceed.");
      return false;
    }
    try {
      setIsBusy(true);
      const docs = await apiFetch<OnboardingResult[]>("/knowledge/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: knowledgePath, parser: "basic" })
      });
      setResult({
        status: "ingested",
        summary: `${docs.length} documents available for search.`
      });
      setResultMessage(`Knowledge ingest finished: ${docs.length} document(s).`);
      await refreshConfiguration();
      return true;
    } catch (error) {
      setResultMessage(error instanceof Error ? error.message : "Knowledge ingest failed.");
      return false;
    } finally {
      setIsBusy(false);
    }
  }

  async function runDemoSummary(): Promise<boolean> {
    if (!ticketId) {
      setResultMessage("Choose or paste a ticket id.");
      return false;
    }
    try {
      setIsBusy(true);
      const summary = await apiFetch<TicketSummaryResponse>(`/tickets/${encodeURIComponent(ticketId)}/summary`);
      setResult({
        status: "demo",
        message: summary.summary ?? "Summary ready.",
        artifact_id: summary.ticket_id
      });
      setResultMessage(`Demo summary created for ${summary.ticket_id}.`);
      return true;
    } catch (error) {
      setResultMessage(error instanceof Error ? error.message : "Ticket demo run failed.");
      return false;
    } finally {
      setIsBusy(false);
    }
  }

  async function handleNext() {
    if (step === 3) {
      const ok = await runIngest();
      if (!ok) {
        return;
      }
      setStep((current) => current + 1);
      return;
    }
    setStep((current) => current + 1);
  }

  async function handleSubmit() {
    await refreshConfiguration();
    onDone();
  }

  return (
    <Wizard
      activeStep={step}
      canContinue={!isBusy}
      isBusy={isBusy}
      onBack={() => setStep((current) => Math.max(0, current - 1))}
      onNext={() => void handleNext()}
      canSubmit={!isBusy}
      onSubmit={() => void handleSubmit()}
      onStepSelect={(index) => {
        if (index <= step) setStep(index);
      }}
      onClose={() => {
        onDismiss();
      }}
      steps={steps}
      progressLabel={resultMessage}
    >
      {step === 0 ? (
        <div className="grid">
          <div className="draft-form">
            <strong>{isAdmin ? "Administrator access is ready." : "Administrator access is required."}</strong>
            <p className="screen-note">
              Create a client record first. The wizard will keep your place while you use the real client screen.
              Connector credentials are never collected or discarded here.
            </p>
            <div className="row-actions">
              <Link className="icon-button" to="/clients?onboarding=1&step=0">Open client configuration</Link>
              {!isAdmin ? <Link className="secondary-button" to="/settings">Open Settings</Link> : null}
            </div>
          </div>
        </div>
      ) : null}

      {step === 1 ? (
        <div className="draft-form">
          <strong>Connect a supported system</strong>
          <p className="screen-note">
            Create the connector instance in the administrator screen. Provider credentials are stored in the local vault there.
          </p>
          <Link className="icon-button" to="/integrations/connector-instances?onboarding=1&step=1">Open connector instance configuration</Link>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="draft-form">
          <strong>Verify ownership before operating</strong>
          <p className="screen-note">
            Select your connector instance, create the external-company mapping, and use Verify. This is the readiness gate for tenant-scoped operations.
          </p>
          <Link className="icon-button" to="/integrations/connector-instances?onboarding=1&step=2#connector-mappings-heading">Open mapping verification</Link>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="draft-form">
          <FolderPicker
            label="Knowledge folder"
            value={knowledgePath}
            onChange={setKnowledgePath}
            placeholder="/path/to/knowledge"
          />
          <p className="screen-note">The path is used for one click onboarding ingest to seed your workspace knowledge.</p>
          <div className="row-actions">
            <button type="button" className="icon-button" onClick={() => void runIngest()}>
              Start ingest now
            </button>
          </div>
          {result.summary ? <p className="screen-note">{result.summary}</p> : null}
        </div>
      ) : null}

      {step === 4 ? (
        <div className="draft-form">
          <label>
            Demo ticket id
            <input
              value={ticketId}
              onChange={(event) => setTicketId(event.target.value)}
              placeholder="TCK-1001"
            />
          </label>
            <p className="screen-note">{result.message ?? "The fixture summary is optional. Run it when the local demo ticket is available, or finish setup now."}</p>
          <button type="button" className="icon-button" onClick={() => void runDemoSummary()}>
            Run ticket summary
          </button>
        </div>
      ) : null}
    </Wizard>
  );
}
