import { useState } from "react";
import { apiFetch } from "../../api/client";
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
  { id: "credentials", title: "Configure connection" },
  { id: "knowledge", title: "Set knowledge folder" },
  { id: "ingest", title: "Import docs from knowledge" },
  { id: "launch-passport", title: "Connect Launch Passport" },
  { id: "demo", title: "Run a demo ticket summary" }
];

export function OnboardingWizard({ onDone, onDismiss }: OnboardingProps) {
  const [step, setStep] = useState(0);
  const [isBusy, setIsBusy] = useState(false);
  const [psa, setPsa] = useState("halopsa");
  const [credentials, setCredentials] = useState("");
  const [knowledgePath, setKnowledgePath] = useState("");
  const [ticketId, setTicketId] = useState("HALO-1");
  const [resultMessage, setResultMessage] = useState("Welcome — complete each setup step to unlock full operations.");
  const [result, setResult] = useState<OnboardingResult>({});

  async function validateConnector(): Promise<boolean> {
    try {
      setIsBusy(true);
      const connectorHealthPaths: Record<string, string> = {
        halopsa: "/connectors/halopsa/health",
        hudu: "/connectors/hudu/health",
        connectwise: "/connectors/connectwise/health",
        "it-glue": "/connectors/itglue/health"
      };
      const endpoint = connectorHealthPaths[psa];
      const health = await apiFetch<{ status: string; message: string }>(endpoint, {
        headers: credentials.trim() ? { Authorization: `Bearer ${credentials.trim()}` } : undefined
      });
      setResultMessage(`${psa.toUpperCase()} status is ${health.status}. ${health.message || "Ready."}`);
      return true;
    } catch (error) {
      setResultMessage(error instanceof Error ? error.message : "Could not validate the connection.");
      return false;
    } finally {
      setIsBusy(false);
    }
  }

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
        body: JSON.stringify({ path: knowledgePath, parser: "local" })
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
    if (step === 0) {
      setStep((current) => current + 1);
      return;
    }
    if (step === 1) {
      const ok = await validateConnector();
      if (!ok) {
        return;
      }
      setStep((current) => current + 1);
      return;
    }
    if (step === 2) {
      setStep((current) => current + 1);
      return;
    }
    if (step === 3) {
      const ok = await runIngest();
      if (!ok) {
        return;
      }
      setStep((current) => current + 1);
      return;
    }
    if (step === 4) {
      setStep((current) => current + 1);
    }
  }

  async function handleSubmit() {
    const ok = await runDemoSummary();
    if (!ok) {
      return;
    }
    onDone();
  }

  return (
    <Wizard
      activeStep={step}
      canContinue={Boolean(psa)}
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
          <p className="screen-note">Each connector is checked against its configured health endpoint. The final demo summary uses the local ticket store; connector-specific reads and approval-gated writes are available from Connectors and Tickets.</p>
        </div>
      ) : null}

      {step === 1 ? (
        <div className="grid">
          <div className="draft-form">
            <label>
              API token
              <input
                type="password"
                autoComplete="new-password"
                placeholder="Paste API token"
                value={credentials}
                onChange={(event) => setCredentials(event.target.value)}
              />
            </label>
            <p>This screen validates your endpoint health and write state with the chosen service.</p>
            <button
              type="button"
              className="icon-button"
              onClick={() => void validateConnector()}
            >
              Validate Connection
            </button>
          </div>
          <p className="screen-note">Store secrets through the local vault in Settings after setup.</p>
        </div>
      ) : null}

      {step === 2 ? (
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

      {step === 3 ? (
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

      {step === 4 ? (
        <div className="draft-form">
          <h3>Connect Launch Passport (optional)</h3>
          <p>Launch Passport helps you review what is ready to share before launch or handoff. This appliance works fully without it.</p>
          <div className="row-actions">
            <button type="button" className="icon-button" onClick={() => setStep(5)}>Skip for now</button>
          </div>
        </div>
      ) : null}

      {step === 5 ? (
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
