import { useState } from "react";
import { AlertTriangle, CheckCircle2, FileJson, PlayCircle, Save, Workflow, XCircle } from "lucide-react";
import { executeEndpointFor, useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { ScopeBadge } from "../components/ScopeBadge";
import type { ApprovalRequest } from "../api/types";
import { fieldsToText, formatPayload, parseFields } from "../lib/fields";

const microsoftAdminRunbookAction = "microsoft_admin.powershell_runbook";

type ExecutionNotice = {
  kind: "success" | "danger";
  message: string;
};

export function Approvals() {
  const {
    approvalRequests,
    pendingApprovals,
    canWrite,
    canWriteExternally = canWrite,
    liveWritesReady,
    isAdmin,
    busyId,
    updateApproval,
    executeApproval,
    savePayloadFields,
    workflowFor,
    refresh,
    loading,
    selectedClientId,
    clients
  } = useDashboard();
  const [draftPayloadFields, setDraftPayloadFields] = useState<Record<number, string>>({});
  const [runbookBusyId, setRunbookBusyId] = useState<number | null>(null);
  const [executionNotices, setExecutionNotices] = useState<Record<number, ExecutionNotice>>({});

  async function executeRequest(request: ApprovalRequest) {
    if (request.action_type !== microsoftAdminRunbookAction) {
      await executeApproval(request.id, request.action_type);
      return;
    }
    setRunbookBusyId(request.id);
    setExecutionNotices((current) => {
      const next = { ...current };
      delete next[request.id];
      return next;
    });
    try {
      const response = await apiFetch<{
        approval: ApprovalRequest;
        result: { status: string; message: string };
      }>(`/packs/microsoft-admin/runbooks/approvals/${request.id}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      setExecutionNotices((current) => ({
        ...current,
        [request.id]: {
          kind: response.result.status === "succeeded" ? "success" : "danger",
          message: response.result.message
        }
      }));
      await refresh();
    } catch (error) {
      setExecutionNotices((current) => ({
        ...current,
        [request.id]: {
          kind: "danger",
          message: error instanceof Error ? error.message : "PowerShell runbook execution failed."
        }
      }));
    } finally {
      setRunbookBusyId(null);
    }
  }

  return (
    <section className="panel approvals-panel">
      <div className="panel-heading">
        <h2>Approval Queue</h2>
        <div><ScopeBadge selectedClientId={selectedClientId} clients={clients} /> <span>{pendingApprovals.length} pending</span></div>
      </div>
      <div className="stack-list">
        {loading ? <LoadingState label="Loading approval requests…" /> : approvalRequests.map((request) => (
          <ApprovalCard
            busy={busyId === request.id || runbookBusyId === request.id}
            canWrite={canWrite}
            canWriteExternally={canWriteExternally}
            liveWritesReady={liveWritesReady}
            isAdmin={isAdmin}
            draftPayloadFields={draftPayloadFields}
            executionNotice={executionNotices[request.id]}
            key={request.id}
            request={request}
            savePayloadFields={savePayloadFields}
            updateApproval={updateApproval}
            executeRequest={executeRequest}
            workflowFor={workflowFor}
            setDraftPayloadFields={setDraftPayloadFields}
          />
        ))}
        {!loading && approvalRequests.length === 0 ? <EmptyState title="No approval requests yet." why="Approval requests appear here when a governed action needs review." /> : null}
      </div>
    </section>
  );
}

type ApprovalCardProps = {
  request: ApprovalRequest;
  busy: boolean;
  canWrite: boolean;
  canWriteExternally: boolean;
  liveWritesReady: boolean;
  isAdmin: boolean;
  draftPayloadFields: Record<number, string>;
  executionNotice?: ExecutionNotice;
  setDraftPayloadFields: (update: (current: Record<number, string>) => Record<number, string>) => void;
  updateApproval: (requestId: number, status: "approved" | "rejected") => Promise<void>;
  executeRequest: (request: ApprovalRequest) => Promise<void>;
  savePayloadFields: (request: ApprovalRequest, fields: Record<string, string>) => Promise<void>;
  workflowFor: (request: ApprovalRequest) => { status: string } | undefined;
};

function ApprovalCard({
  request,
  busy,
  canWrite,
  canWriteExternally,
  liveWritesReady,
  isAdmin,
  draftPayloadFields,
  executionNotice,
  setDraftPayloadFields,
  updateApproval,
  executeRequest,
  savePayloadFields,
  workflowFor
}: ApprovalCardProps) {
  const payloadText = draftPayloadFields[request.id] ?? fieldsToText(request.payload?.fields);
  const workflow = workflowFor(request);
  const isRunbook = request.action_type === microsoftAdminRunbookAction;
  const canExecute = request.status === "approved" && (
    isRunbook
      ? request.execution_status === "not_started"
      : Boolean(request.can_execute)
  );
  const hasExecuteEndpoint = isRunbook || executeEndpointFor(request.action_type) !== null;
  const roleCanExecute = !isRunbook || isAdmin;
  const visibleBlockReason = isRunbook ? "" : request.block_reason;
  const executionCompleted = ["succeeded", "verified", "unverified", "submitted"].includes(request.execution_status);
  const executeHint = request.block_reason || (!canWrite
    ? "Requires technician access"
    : !canWriteExternally
      ? "External writes are disabled in Safe Mode"
    : !roleCanExecute
      ? "Requires administrator access"
      : request.action_type.startsWith("halopsa.") &&
          request.status === "approved" &&
          !executionCompleted &&
          !canExecute &&
          !liveWritesReady
        ? "Writes are in Safe Mode — see the write-gate indicator"
        : undefined);

  return (
    <div className="approval-card">
      <div className="approval-main">
        <div>
          <strong>{request.action_type}</strong>
          <span>{request.subject_id}</span>
        </div>
        <em>{request.status} / {request.execution_status}</em>
      </div>
      <p>{request.execution_message || request.comment || "Waiting for review"}</p>
      {request.expires_at ? <p className="screen-note">Approval deadline: {request.expires_at}</p> : null}
      {visibleBlockReason ? (
        <div className="blocked-reason">
          <AlertTriangle size={15} aria-hidden="true" />
          {visibleBlockReason}
        </div>
      ) : null}
      {executionNotice ? (
        <div className={`notice ${executionNotice.kind}`} role={executionNotice.kind === "danger" ? "alert" : "status"}>
          {executionNotice.message}
        </div>
      ) : null}
      <div className="payload-grid">
        <div className="payload-preview">
          <h3><FileJson size={16} aria-hidden="true" />Payload Preview</h3>
          <pre>{formatPayload(request.payload)}</pre>
        </div>
        {isRunbook ? (
          <div className="payload-editor">
            <strong>Digest-bound plan</strong>
            <p className="screen-note">
              Runbook parameters cannot be edited after draft creation. Reject this request and create a new draft to change them.
            </p>
          </div>
        ) : (
          <label className="payload-editor">
            Draft Fields
            <textarea
              disabled={!canWrite || request.status !== "pending"}
              rows={6}
              value={payloadText}
              onChange={(event) => setDraftPayloadFields((current) => ({ ...current, [request.id]: event.target.value }))}
            />
          </label>
        )}
      </div>
      <div className="workflow-link">
        <Workflow size={15} aria-hidden="true" />
        {request.workflow_run_id ? (
          <span>
            Workflow run {request.workflow_run_id}
            {workflow ? `: ${workflow.status}` : ""}
          </span>
        ) : <span>No workflow run linked</span>}
      </div>
      {isRunbook && !isAdmin ? (
        <p className="screen-note">PowerShell runbook execution requires administrator access.</p>
      ) : null}
      <div className="row-actions">
        {canWrite ? (
          <>
            {!isRunbook ? (
              <button
                className="icon-button"
                disabled={busy || request.status !== "pending"}
                type="button"
                onClick={() => void savePayloadFields(request, parseFields(payloadText))}
              >
                <Save size={16} aria-hidden="true" />
                Save Fields
              </button>
            ) : null}
            <button
              disabled={busy || request.status !== "pending"}
              type="button"
              onClick={() => void updateApproval(request.id, "approved")}
            >
              <CheckCircle2 size={16} aria-hidden="true" />
              Approve
            </button>
            <button
              disabled={busy || request.status !== "pending"}
              type="button"
              onClick={() => void updateApproval(request.id, "rejected")}
            >
              <XCircle size={16} aria-hidden="true" />
              Reject
            </button>
          </>
        ) : null}
        {hasExecuteEndpoint ? (
          <button
            disabled={busy || !canWriteExternally || !canExecute || !hasExecuteEndpoint || !roleCanExecute}
            title={executeHint}
            type="button"
            onClick={() => void executeRequest(request)}
          >
            <PlayCircle size={16} aria-hidden="true" />
            Execute
          </button>
        ) : (
          <p className="screen-note">Executed from its own workflow after approval — no manual execute here.</p>
        )}
      </div>
    </div>
  );
}
