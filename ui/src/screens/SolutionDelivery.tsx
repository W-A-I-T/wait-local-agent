import { useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, CheckCircle2, Circle, FileJson, PackageOpen, PlayCircle, RefreshCw, RotateCcw, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { executeEndpointFor, useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { ClientIdSelect } from "../components/ClientIdSelect";
import type { ApprovalRequest } from "../api/types";

type JsonRecord = Record<string, unknown>;
type GateStatus = "met" | "unmet" | "unknown";
type GateState = {
  deployment: GateStatus;
  writes: GateStatus;
  pac: GateStatus;
  workspace: GateStatus;
};

type PackageForm = {
  clientId: string;
  solutionName: string;
  publisherName: string;
  publisherPrefix: string;
  outputDirectory: string;
  artifacts: string;
  connectorArtifacts: string;
};

type DeploymentForm = {
  clientId: string;
  solutionName: string;
  publisherName: string;
  publisherPrefix: string;
  outputDirectory: string;
  deploymentTargets: string;
  stage: "build" | "dev" | "test" | "prod";
  promotionEvidence: string;
};

type RollbackForm = {
  clientId: string;
  solutionName: string;
  publisherName: string;
  publisherPrefix: string;
  outputDirectory: string;
  deploymentTargets: string;
  stage: "dev" | "test" | "prod";
  rollbackArtifactPath: string;
  rollbackEvidence: string;
};

type PackageArtifact = JsonRecord & {
  package_digest?: string;
  file_count?: number;
  client_id?: string;
  solution?: JsonRecord;
};

type ApprovalCreateResponse = {
  approval: ApprovalRequest;
  plan: JsonRecord;
};

const initialGates: GateState = {
  deployment: "unknown",
  writes: "unknown",
  pac: "unknown",
  workspace: "unknown",
};

const initialPackageForm: PackageForm = {
  clientId: "",
  solutionName: "employee_onboarding",
  publisherName: "WAIT",
  publisherPrefix: "wait",
  outputDirectory: "/path/inside/WAIT_POWER_PLATFORM_WORKSPACE/employee_onboarding",
  artifacts: "[]",
  connectorArtifacts: "[]",
};

const initialDeploymentForm: DeploymentForm = {
  clientId: "",
  solutionName: "employee_onboarding",
  publisherName: "WAIT",
  publisherPrefix: "wait",
  outputDirectory: "/path/inside/WAIT_POWER_PLATFORM_WORKSPACE/employee_onboarding",
  deploymentTargets: JSON.stringify([{ name: "dev", environment_url: "https://dev.example.invalid" }], null, 2),
  stage: "build",
  promotionEvidence: "{}",
};

const initialRollbackForm: RollbackForm = {
  clientId: "",
  solutionName: "employee_onboarding",
  publisherName: "WAIT",
  publisherPrefix: "wait",
  outputDirectory: "/path/inside/WAIT_POWER_PLATFORM_WORKSPACE/employee_onboarding",
  deploymentTargets: JSON.stringify([{ name: "dev", environment_url: "https://dev.example.invalid" }], null, 2),
  stage: "dev",
  rollbackArtifactPath: "",
  rollbackEvidence: JSON.stringify({ available: true, strategy: "reimport_previous_package", artifact_digest: "sha256:" }, null, 2),
};

const deploymentAction = "power_platform.solution_stage";
const rollbackAction = "power_platform.solution_rollback";

export function SolutionDelivery() {
  const {
    approvalRequests,
    canWrite,
    clients = [],
    clientId: scopedClientId,
    executeApproval,
    isAdmin,
    refresh,
  } = useDashboard();
  const defaultClientId = scopedClientId.trim();
  const [packageForm, setPackageForm] = useState<PackageForm>({ ...initialPackageForm, clientId: defaultClientId });
  const [deploymentForm, setDeploymentForm] = useState<DeploymentForm>({ ...initialDeploymentForm, clientId: defaultClientId });
  const [rollbackForm, setRollbackForm] = useState<RollbackForm>({ ...initialRollbackForm, clientId: defaultClientId });
  const [packageArtifact, setPackageArtifact] = useState<PackageArtifact | null>(null);
  const [validationResult, setValidationResult] = useState<JsonRecord | null>(null);
  const [materializationResult, setMaterializationResult] = useState<JsonRecord | null>(null);
  const [deploymentPlan, setDeploymentPlan] = useState<JsonRecord | null>(null);
  const [rollbackApproval, setRollbackApproval] = useState<ApprovalRequest | null>(null);
  const [gates, setGates] = useState<GateState>(initialGates);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [rollbackBusyId, setRollbackBusyId] = useState<number | null>(null);

  useEffect(() => {
    if (!defaultClientId) return;
    setPackageForm((current) => current.clientId ? current : { ...current, clientId: defaultClientId });
    setDeploymentForm((current) => current.clientId ? current : { ...current, clientId: defaultClientId });
    setRollbackForm((current) => current.clientId ? current : { ...current, clientId: defaultClientId });
  }, [defaultClientId]);

  useEffect(() => {
    setGates((current) => approvalRequests.reduce(
      (state, request) => mergeGateObservation(state, request.block_reason, request.can_execute === true),
      current,
    ));
  }, [approvalRequests]);

  const powerPlatformApprovals = approvalRequests.filter(
    (request) => request.action_type === deploymentAction || request.action_type === rollbackAction,
  );

  function effectiveClientId(value: string): string {
    return value.trim() || defaultClientId;
  }

  async function buildPackage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("package");
    setMessage("");
    try {
      const result = await apiFetch<PackageArtifact>("/consultant/power-platform/package", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: required(effectiveClientId(packageForm.clientId), "Client workspace ID"),
          solution_name: required(packageForm.solutionName, "Solution name"),
          publisher_name: required(packageForm.publisherName, "Publisher name"),
          publisher_prefix: required(packageForm.publisherPrefix, "Publisher prefix"),
          output_directory: required(packageForm.outputDirectory, "Output directory"),
          artifacts: parseArray(packageForm.artifacts, "Artifacts"),
          connector_artifacts: parseArray(packageForm.connectorArtifacts, "Connector artifacts"),
        }),
      });
      setPackageArtifact(result);
      setValidationResult(null);
      setMaterializationResult(null);
      setMessage("Credential-free Power Platform source package is ready to validate.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The package could not be built.");
    } finally {
      setBusy(null);
    }
  }

  async function validatePackage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!packageArtifact) {
      setMessage("Build a package before validating it.");
      return;
    }
    setBusy("validate");
    setMessage("");
    try {
      const result = await apiFetch<JsonRecord>("/consultant/power-platform/package/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: effectiveClientId(packageForm.clientId) || undefined, package: packageArtifact }),
      });
      setValidationResult(result);
      setMessage("Package validation passed. No execution or deployment was started.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The package could not be validated.");
    } finally {
      setBusy(null);
    }
  }

  async function materializePackage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!packageArtifact) {
      setMessage("Build a package before materializing it.");
      return;
    }
    setBusy("materialize");
    setMessage("");
    try {
      const result = await apiFetch<JsonRecord>("/consultant/power-platform/package/materialize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: effectiveClientId(packageForm.clientId) || undefined, package: packageArtifact }),
      });
      setMaterializationResult(result);
      observeGateResponse(result, "materialize");
      setMessage(typeof result.message === "string" ? result.message : "Package materialization returned.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The package could not be materialized.");
    } finally {
      setBusy(null);
    }
  }

  async function requestDeploymentApproval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("deployment");
    setMessage("");
    try {
      const result = await apiFetch<ApprovalCreateResponse>("/consultant/solutions/deployment-approvals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: required(effectiveClientId(deploymentForm.clientId), "Client workspace ID"),
          solution_name: required(deploymentForm.solutionName, "Deployment solution name"),
          publisher_name: required(deploymentForm.publisherName, "Deployment publisher name"),
          publisher_prefix: required(deploymentForm.publisherPrefix, "Deployment publisher prefix"),
          output_directory: required(deploymentForm.outputDirectory, "Deployment output directory"),
          deployment_targets: parseArray(deploymentForm.deploymentTargets, "Deployment targets"),
          stage: deploymentForm.stage,
          promotion_evidence: parseObject(deploymentForm.promotionEvidence, "Promotion evidence"),
        }),
      });
      setDeploymentPlan(result.plan);
      observeGateResponse(result.approval);
      setMessage(`Deployment approval #${result.approval.id} is ${result.approval.status}. Review it before execution.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The deployment approval could not be created.");
    } finally {
      setBusy(null);
    }
  }

  async function requestRollbackApproval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("rollback");
    setMessage("");
    try {
      const result = await apiFetch<ApprovalCreateResponse>("/consultant/solutions/rollback-approvals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: required(effectiveClientId(rollbackForm.clientId), "Client workspace ID"),
          solution_name: required(rollbackForm.solutionName, "Rollback solution name"),
          publisher_name: required(rollbackForm.publisherName, "Rollback publisher name"),
          publisher_prefix: required(rollbackForm.publisherPrefix, "Rollback publisher prefix"),
          output_directory: required(rollbackForm.outputDirectory, "Rollback output directory"),
          deployment_targets: parseArray(rollbackForm.deploymentTargets, "Rollback deployment targets"),
          stage: rollbackForm.stage,
          rollback_artifact_path: required(rollbackForm.rollbackArtifactPath, "Rollback artifact path"),
          rollback_evidence: parseObject(rollbackForm.rollbackEvidence, "Rollback evidence"),
        }),
      });
      setRollbackApproval(result.approval);
      setMessage(`Rollback approval #${result.approval.id} is ${result.approval.status}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The rollback approval could not be created.");
    } finally {
      setBusy(null);
    }
  }

  async function executeStage(request: ApprovalRequest) {
    if (!isAdmin || executeEndpointFor(request.action_type) === null) return;
    if (!window.confirm(`Execute the approved ${stageFor(request)} Power Platform stage?`)) return;
    setBusy(`execute-${request.id}`);
    setMessage("");
    try {
      await executeApproval(request.id, request.action_type);
      setMessage(`Execution requested for approval #${request.id}.`);
    } finally {
      setBusy(null);
    }
  }

  async function requestRollbackFor(request: ApprovalRequest) {
    const payload = request.payload ?? {};
    const stage = stageFor(request);
    const outputDirectory = stringValue(payload.output_directory);
    const solutionName = stringValue(payload.solution_name);
    const output = request.output ?? {};
    const rollbackEvidence = asRecord(asRecord(payload.promotion_evidence)?.rollback);
    const digest = stringValue(output.artifact_digest) || stringValue(rollbackEvidence?.artifact_digest);
    if (!isDeploymentApproval(request) || !["dev", "test", "prod"].includes(stage) || request.execution_status !== "succeeded" || !outputDirectory || !solutionName || !digest) {
      setMessage("Rollback evidence is available only after a successful stage with a verified artifact digest.");
      return;
    }
    if (!window.confirm(`Request a rollback approval for the ${stage.toUpperCase()} environment?`)) return;
    setRollbackBusyId(request.id);
    setMessage("");
    try {
      const result = await apiFetch<ApprovalCreateResponse>("/consultant/solutions/rollback-approvals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: stringValue(payload.client_id),
          solution_name: solutionName,
          publisher_name: stringValue(payload.publisher_name),
          publisher_prefix: stringValue(payload.publisher_prefix),
          output_directory: outputDirectory,
          deployment_targets: payload.deployment_targets,
          stage,
          rollback_artifact_path: `${outputDirectory.replace(/\/$/, "")}/${solutionName}.zip`,
          rollback_evidence: { available: true, strategy: "reimport_previous_package", artifact_digest: digest },
        }),
      });
      setRollbackApproval(result.approval);
      setMessage(`Rollback approval #${result.approval.id} is ${result.approval.status}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The rollback approval could not be created.");
    } finally {
      setRollbackBusyId(null);
    }
  }

  function observeGateResponse(value: unknown, source?: "materialize") {
    const response = asRecord(value);
    const approval = asRecord(response?.approval) ?? response;
    const reason = stringValue(approval?.block_reason) || stringValue(response?.message);
    const executable = approval?.can_execute === true;
    setGates((current) => {
      const next = mergeGateObservation(current, reason, executable);
      if (source === "materialize" && response?.status === "succeeded") next.writes = "met";
      return next;
    });
  }

  return (
    <div className="screen-stack solution-delivery-screen">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Solution delivery</h2>
            <p className="screen-note"><ShieldCheck size={16} aria-hidden="true" /> Governed, approval-backed Power Platform delivery.</p>
          </div>
          <div className="row-actions">
            <Link className="inline-link" to="/approvals">Open Approvals</Link>
            <button className="icon-button" type="button" onClick={() => void refresh()}><RefreshCw size={16} aria-hidden="true" /> Refresh</button>
          </div>
        </div>
        <div className="notice">
          <strong>Local operator boundary.</strong> Deploys via your locally-authenticated pac CLI. Nothing runs until WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT and WAIT_ALLOW_WRITE_ACTIONS are enabled and each stage is approved.
        </div>
        {message ? <div className="notice danger" role="alert"><AlertTriangle size={16} aria-hidden="true" />{message}</div> : null}
        <ol className="solution-pipeline" aria-label="Solution delivery pipeline">
          <PipelineStep label="Package" done={Boolean(packageArtifact)} active={!packageArtifact} />
          <PipelineStep label="Validate" done={Boolean(validationResult)} active={Boolean(packageArtifact) && !validationResult} />
          <PipelineStep label="Materialize" done={materializationResult?.status === "succeeded"} active={Boolean(validationResult) && !materializationResult} />
          <PipelineStep label="Deploy stages" done={Boolean(deploymentPlan)} active={Boolean(materializationResult) && !deploymentPlan} />
          <PipelineStep label="Rollback" done={Boolean(rollbackApproval)} active={Boolean(deploymentPlan) && !rollbackApproval} />
        </ol>
      </section>

      <GateBanner gates={gates} />

      <section className="panel delivery-step-panel">
        <div className="panel-heading"><div><h2><PackageOpen size={18} aria-hidden="true" /> 1. Package</h2><p className="screen-note">Create deterministic, credential-free YAML source in memory.</p></div></div>
        <form className="draft-form" onSubmit={(event) => void buildPackage(event)}>
          <div className="grid">
            <ClientIdSelect label="Client workspace ID" value={packageForm.clientId} onChange={(value) => setPackageForm((current) => ({ ...current, clientId: value }))} clients={clients} required id="package-client-id" />
            <TextField label="Solution name" value={packageForm.solutionName} onChange={(value) => setPackageForm((current) => ({ ...current, solutionName: value }))} />
            <TextField label="Publisher name" value={packageForm.publisherName} onChange={(value) => setPackageForm((current) => ({ ...current, publisherName: value }))} />
            <TextField label="Publisher prefix" value={packageForm.publisherPrefix} onChange={(value) => setPackageForm((current) => ({ ...current, publisherPrefix: value }))} />
            <TextField label="Output directory" value={packageForm.outputDirectory} onChange={(value) => setPackageForm((current) => ({ ...current, outputDirectory: value }))} />
            <JsonField label="Artifacts (JSON array)" value={packageForm.artifacts} onChange={(value) => setPackageForm((current) => ({ ...current, artifacts: value }))} />
            <JsonField label="Connector artifacts (JSON array)" value={packageForm.connectorArtifacts} onChange={(value) => setPackageForm((current) => ({ ...current, connectorArtifacts: value }))} />
          </div>
          <button type="submit" disabled={!canWrite || busy !== null}>{busy === "package" ? "Packaging…" : "Build package"}</button>
          {!canWrite ? <p className="screen-note">Technician access is required to create a package.</p> : null}
        </form>
        {packageArtifact ? <ResultSummary title="Package ready" value={packageArtifact} detail={`${packageArtifact.file_count ?? 0} files · ${packageArtifact.package_digest ?? "digest pending"}`} /> : null}
      </section>

      <section className="panel delivery-step-panel">
        <div className="panel-heading"><div><h2><FileJson size={18} aria-hidden="true" /> 2. Validate</h2><p className="screen-note">Re-check the digest-bound package before any local write.</p></div></div>
        <form className="row-actions" onSubmit={(event) => void validatePackage(event)}>
          <button type="submit" disabled={!packageArtifact || busy !== null}>{busy === "validate" ? "Validating…" : "Validate package"}</button>
        </form>
        {validationResult ? <ResultSummary title="Validation passed" value={validationResult} detail="deployable: true · execution_started: false · deployment_started: false" /> : null}
      </section>

      <section className="panel delivery-step-panel">
        <div className="panel-heading"><div><h2><ShieldCheck size={18} aria-hidden="true" /> 3. Materialize</h2><p className="screen-note">Write source files only after the admin-gated endpoint accepts the package.</p></div></div>
        <form className="row-actions" onSubmit={(event) => void materializePackage(event)}>
          <button type="submit" disabled={!packageArtifact || !isAdmin || busy !== null}>{busy === "materialize" ? "Materializing…" : "Materialize source"}</button>
        </form>
        {!isAdmin ? <p className="screen-note">Administrator access is required to materialize source files.</p> : null}
        {materializationResult ? <ResultSummary title="Materialization response" value={materializationResult} detail={stringValue(materializationResult.message)} /> : null}
      </section>

      <section className="panel delivery-step-panel">
        <div className="panel-heading"><div><h2><PlayCircle size={18} aria-hidden="true" /> 4. Deployment approvals</h2><p className="screen-note">Request one approval per ordered build, DEV, TEST, or PROD stage.</p></div></div>
        <form className="draft-form" onSubmit={(event) => void requestDeploymentApproval(event)}>
          <div className="grid">
            <ClientIdSelect label="Deployment client workspace ID" value={deploymentForm.clientId} onChange={(value) => setDeploymentForm((current) => ({ ...current, clientId: value }))} clients={clients} required id="deployment-client-id" />
            <TextField label="Deployment solution name" value={deploymentForm.solutionName} onChange={(value) => setDeploymentForm((current) => ({ ...current, solutionName: value }))} />
            <TextField label="Deployment publisher name" value={deploymentForm.publisherName} onChange={(value) => setDeploymentForm((current) => ({ ...current, publisherName: value }))} />
            <TextField label="Deployment publisher prefix" value={deploymentForm.publisherPrefix} onChange={(value) => setDeploymentForm((current) => ({ ...current, publisherPrefix: value }))} />
            <TextField label="Deployment output directory" value={deploymentForm.outputDirectory} onChange={(value) => setDeploymentForm((current) => ({ ...current, outputDirectory: value }))} />
            <label>Deployment stage<select value={deploymentForm.stage} onChange={(event) => setDeploymentForm((current) => ({ ...current, stage: event.target.value as DeploymentForm["stage"] }))}><option value="build">Build</option><option value="dev">DEV</option><option value="test">TEST</option><option value="prod">PROD</option></select></label>
            <JsonField label="Deployment targets (JSON array)" value={deploymentForm.deploymentTargets} onChange={(value) => setDeploymentForm((current) => ({ ...current, deploymentTargets: value }))} />
            <JsonField label="Promotion evidence (JSON object)" value={deploymentForm.promotionEvidence} onChange={(value) => setDeploymentForm((current) => ({ ...current, promotionEvidence: value }))} />
          </div>
          <button type="submit" disabled={!canWrite || busy !== null}>{busy === "deployment" ? "Requesting…" : "Request stage approval"}</button>
        </form>
        {deploymentPlan ? <ResultSummary title="Deployment plan" value={deploymentPlan} detail="Planning is metadata-only; deployment_started: false." /> : null}
      </section>

      <section className="panel delivery-step-panel">
        <div className="panel-heading"><div><h2><RotateCcw size={18} aria-hidden="true" /> 5. Rollback approval</h2><p className="screen-note">Choose the prior ZIP explicitly; WAIT never selects a rollback artifact automatically.</p></div></div>
        <form className="draft-form" onSubmit={(event) => void requestRollbackApproval(event)}>
          <div className="grid">
            <ClientIdSelect label="Rollback client workspace ID" value={rollbackForm.clientId} onChange={(value) => setRollbackForm((current) => ({ ...current, clientId: value }))} clients={clients} required id="rollback-client-id" />
            <TextField label="Rollback solution name" value={rollbackForm.solutionName} onChange={(value) => setRollbackForm((current) => ({ ...current, solutionName: value }))} />
            <TextField label="Rollback publisher name" value={rollbackForm.publisherName} onChange={(value) => setRollbackForm((current) => ({ ...current, publisherName: value }))} />
            <TextField label="Rollback publisher prefix" value={rollbackForm.publisherPrefix} onChange={(value) => setRollbackForm((current) => ({ ...current, publisherPrefix: value }))} />
            <TextField label="Rollback output directory" value={rollbackForm.outputDirectory} onChange={(value) => setRollbackForm((current) => ({ ...current, outputDirectory: value }))} />
            <TextField label="Rollback artifact path" value={rollbackForm.rollbackArtifactPath} onChange={(value) => setRollbackForm((current) => ({ ...current, rollbackArtifactPath: value }))} />
            <label>Rollback stage<select value={rollbackForm.stage} onChange={(event) => setRollbackForm((current) => ({ ...current, stage: event.target.value as RollbackForm["stage"] }))}><option value="dev">DEV</option><option value="test">TEST</option><option value="prod">PROD</option></select></label>
            <JsonField label="Rollback deployment targets (JSON array)" value={rollbackForm.deploymentTargets} onChange={(value) => setRollbackForm((current) => ({ ...current, deploymentTargets: value }))} />
            <JsonField label="Rollback evidence (JSON object)" value={rollbackForm.rollbackEvidence} onChange={(value) => setRollbackForm((current) => ({ ...current, rollbackEvidence: value }))} />
          </div>
          <button type="submit" disabled={!canWrite || busy !== null}>{busy === "rollback" ? "Requesting…" : "Request rollback approval"}</button>
        </form>
        {rollbackApproval ? <ResultSummary title="Rollback approval" value={rollbackApproval} detail={`Approval #${rollbackApproval.id} · ${rollbackApproval.status}`} /> : null}
      </section>

      <section className="panel approvals-panel">
        <div className="panel-heading"><div><h2>Deployment approvals</h2><p className="screen-note">Tenant-scoped stage and rollback approvals from the shared approval feed.</p></div><span>{powerPlatformApprovals.length} found</span></div>
        <div className="stack-list">
          {powerPlatformApprovals.map((request) => <DeliveryApprovalCard key={request.id} request={request} canExecute={isAdmin && canWrite && request.can_execute === true} busy={busy === `execute-${request.id}`} rollbackBusy={rollbackBusyId === request.id} onExecute={() => void executeStage(request)} onRollback={() => void requestRollbackFor(request)} />)}
          {powerPlatformApprovals.length === 0 ? <p className="screen-note">No Power Platform approvals are in the feed yet.</p> : null}
        </div>
      </section>
    </div>
  );
}

function PipelineStep({ label, done, active }: { label: string; done: boolean; active: boolean }) {
  return <li className={`solution-pipeline-step ${done ? "done" : ""} ${active ? "active" : ""}`}><span>{done ? <CheckCircle2 size={16} aria-hidden="true" /> : <Circle size={16} aria-hidden="true" />}</span>{label}</li>;
}

function GateBanner({ gates }: { gates: GateState }) {
  return (
    <section className="panel solution-gates" aria-labelledby="solution-gates-heading">
      <div className="panel-heading"><div><h2 id="solution-gates-heading">Backend gate state</h2><p className="screen-note">These indicators reflect backend responses and approval block reasons; the UI does not re-implement the gates.</p></div></div>
      <div className="solution-gate-grid">
        <Gate label="WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT" status={gates.deployment} />
        <Gate label="WAIT_ALLOW_WRITE_ACTIONS" status={gates.writes} />
        <Gate label="pac on the local PATH" status={gates.pac} />
        <Gate label="WAIT_POWER_PLATFORM_WORKSPACE" status={gates.workspace} />
      </div>
    </section>
  );
}

function Gate({ label, status }: { label: string; status: GateStatus }) {
  const text = status === "met" ? "Met" : status === "unmet" ? "Unmet" : "Not checked";
  return <div className={`solution-gate ${status}`}><strong>{label}</strong><span>{text}</span></div>;
}

function DeliveryApprovalCard({
  request,
  canExecute,
  busy,
  rollbackBusy,
  onExecute,
  onRollback,
}: {
  request: ApprovalRequest;
  canExecute: boolean;
  busy: boolean;
  rollbackBusy: boolean;
  onExecute: () => void;
  onRollback: () => void;
}) {
  const payload = request.payload ?? {};
  const stage = stageFor(request);
  const targets = Array.isArray(payload.deployment_targets) ? payload.deployment_targets : [];
  const target = targets.find((item) => asRecord(item)?.name === stage);
  const environmentUrl = stringValue(asRecord(target)?.environment_url);
  const evidence = asRecord(payload.promotion_evidence);
  const digest = stringValue(evidence?.artifact_digest);
  const sourceApproval = stringValue(evidence?.source_approval_request_id);
  const outputDigest = stringValue(request.output?.artifact_digest);
  const rollbackReady = request.action_type === deploymentAction && ["dev", "test", "prod"].includes(stage) && request.execution_status === "succeeded" && Boolean(outputDigest || asRecord(evidence?.rollback)?.artifact_digest);
  return (
    <article className="approval-card solution-approval-card">
      <div className="approval-main"><div><strong>{request.action_type === deploymentAction ? "Stage" : "Rollback"}: {stage.toUpperCase()}</strong><span>{request.subject_id}</span></div><em>{request.status} / {request.execution_status}</em></div>
      {environmentUrl ? <p><strong>Environment:</strong> <code>{environmentUrl}</code></p> : null}
      <div className="solution-evidence"><span>Promotion digest: <code>{digest || "not supplied"}</code></span><span>Prior-stage approval: <code>{sourceApproval || "not required"}</code></span><span>Artifact digest: <code>{outputDigest || "not recorded"}</code></span></div>
      {request.block_reason ? <div className="blocked-reason"><AlertTriangle size={15} aria-hidden="true" />{request.block_reason}</div> : null}
      <div className="row-actions">
        <button type="button" disabled={!canExecute || busy} onClick={onExecute}><PlayCircle size={16} aria-hidden="true" />{busy ? "Executing…" : request.action_type === deploymentAction ? "Execute stage" : "Execute rollback"}</button>
        {rollbackReady ? <button className="secondary-button" type="button" disabled={rollbackBusy} onClick={onRollback}><RotateCcw size={16} aria-hidden="true" />{rollbackBusy ? "Requesting…" : "Request rollback"}</button> : null}
      </div>
    </article>
  );
}

function ResultSummary({ title, value, detail }: { title: string; value: unknown; detail: string }) {
  return <div className="solution-result"><strong>{title}</strong><span>{detail}</span><details><summary>Show response</summary><pre>{JSON.stringify(value, null, 2)}</pre></details></div>;
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label>{label}<input value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function JsonField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label>{label}<textarea rows={4} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function required(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${label} is required.`);
  return normalized;
}

function parseJson(value: string, label: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
}

function parseArray(value: string, label: string): unknown[] {
  const parsed = parseJson(value, label);
  if (!Array.isArray(parsed)) throw new Error(`${label} must be a JSON array.`);
  return parsed;
}

function parseObject(value: string, label: string): JsonRecord {
  const parsed = parseJson(value, label);
  if (!asRecord(parsed)) throw new Error(`${label} must be a JSON object.`);
  return asRecord(parsed) as JsonRecord;
}

function asRecord(value: unknown): JsonRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stageFor(request: ApprovalRequest): string {
  return stringValue(request.payload?.stage) || (request.action_type === rollbackAction ? "rollback" : "build");
}

function isDeploymentApproval(request: ApprovalRequest): boolean {
  return request.action_type === deploymentAction;
}

function mergeGateObservation(state: GateState, reason: string | undefined, executable: boolean): GateState {
  if (executable) return { deployment: "met", writes: "met", pac: "met", workspace: "met" };
  return mergeGateReason(state, reason ?? "");
}

function mergeGateReason(state: GateState, reason: string): GateState {
  const next = { ...state };
  if (reason.includes("WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT")) next.deployment = "unmet";
  if (reason.includes("WAIT_ALLOW_WRITE_ACTIONS")) next.writes = "unmet";
  if (reason.includes("pac executable")) next.pac = "unmet";
  if (reason.includes("WAIT_POWER_PLATFORM_WORKSPACE")) next.workspace = "unmet";
  return next;
}
