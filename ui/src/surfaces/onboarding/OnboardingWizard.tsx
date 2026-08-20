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
};

const steps: WizardStep[] = [
  { id: "connector", title: "Choose your primary PSA" },
  { id: "knowledge", title: "Set knowledge folder" },
  { id: "ingest", title: "Import docs from knowledge" },
  { id: "demo", title: "Run a demo ticket summary" }
];

export function OnboardingWizard({ onDone, onDismiss }: OnboardingProps) {
  const { refresh = async () => {} } = useDashboard();
  const [step, setStep] = useState(0);
  const [isBusy, setIsBusy] = useState(false);
  const [psa, setPsa] = useState("halopsa");
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
    if (step === 2) {
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
    const ok = await runDemoSummary();
    if (!ok) {
      return;
    }
    await refresh();
    onDone();
  }

  return (
    <Wizard
      activeStep={step}
      canContinue={!isBusy && Boolean(psa)}
      isBusy={isBusy}
      onBack={() => setStep((current) => Math.max(0, current - 1))}
      onNext={() => void handleNext()}
      canSubmit={!!ticketId && !isBusy}
      onSubmit={() => void handleSubmit()}
      onClose={() => {
        onDismiss();
      }}
      steps={steps}
      progressLabel={resultMessage}
    >
      {step === 0 ? (
        <div className="grid">
          <label className="draft-form">
            <strong>Choose your primary service connector</strong>
            <select value={psa} onChange={(event) => setPsa(event.target.value)}>
              <option value="halopsa">HaloPSA</option>
              <option value="hudu">Hudu</option>
              <option value="connectwise">ConnectWise PSA</option>
              <option value="it-glue">IT Glue documentation</option>
            </select>
          </label>
          <p className="screen-note">Choose a connector, then configure and verify it from the real connector screen. This wizard never stores or discards provider credentials.</p>
          <Link className="icon-button" to="/connectors">Open connector configuration</Link>
        </div>
      ) : null}

      {step === 1 ? (
        <div className="draft-form">
          <FolderPicker
            label="Knowledge folder"
            value={knowledgePath}
            onChange={setKnowledgePath}
            placeholder="/path/to/knowledge"
          />
          <p className="screen-note">The path is used for one click onboarding ingest to seed your workspace knowledge.</p>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="draft-form">
          <p>{knowledgePath ? `Ready to ingest from ${knowledgePath}` : "Set a knowledge folder first."}</p>
          <div className="row-actions">
            <button type="button" className="icon-button" onClick={() => void runIngest()}>
              Start ingest now
            </button>
          </div>
          {result.summary ? <p className="screen-note">{result.summary}</p> : null}
        </div>
      ) : null}

      {step === 3 ? (
        <div className="draft-form">
          <label>
            Demo ticket id
            <input
              value={ticketId}
              onChange={(event) => setTicketId(event.target.value)}
              placeholder="HALO-1234"
            />
          </label>
          <p className="screen-note">{result.message ?? "Run a safe demo summary call before moving into live actions."}</p>
          <button type="button" className="icon-button" onClick={() => void runDemoSummary()}>
            Run ticket summary
          </button>
        </div>
      ) : null}
    </Wizard>
  );
}
