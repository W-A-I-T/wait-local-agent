import { useState } from "react";
import { AlertTriangle, CheckCircle2, FileJson, PlayCircle, Save, Workflow, XCircle } from "lucide-react";
import { useDashboard } from "../app/DashboardContext";
import type { ApprovalRequest } from "../api/types";
import { fieldsToText, formatPayload, parseFields } from "../lib/fields";

export function Approvals() {
  const {
    approvalRequests,
    pendingApprovals,
    canWrite,
    busyId,
    updateApproval,
    executeApproval,
    savePayloadFields,
    workflowFor,
    liveWritesReady
  } = useDashboard();
  const [draftPayloadFields, setDraftPayloadFields] = useState<Record<number, string>>({});

  return (
    <section className="panel approvals-panel">
      <div className="panel-heading">
        <h2>Approval Queue</h2>
        <span>{pendingApprovals.length} pending</span>
      </div>
      <div className="stack-list">
        {approvalRequests.map((request) => (
          <ApprovalCard
            busyId={busyId}
            canWrite={canWrite}
            draftPayloadFields={draftPayloadFields}
            key={request.id}
            liveWritesReady={liveWritesReady}
            request={request}
            setDraftPayloadFields={setDraftPayloadFields}
            updateApproval={updateApproval}
            executeApproval={executeApproval}
            savePayloadFields={savePayloadFields}
            workflowFor={workflowFor}
          />
        ))}
        {approvalRequests.length === 0 ? <p>No approval requests yet.</p> : null}
      </div>
    </section>
  );
}

type ApprovalCardProps = {
  request: ApprovalRequest;
  busyId: number | "draft" | null;
  canWrite: boolean;
  liveWritesReady: boolean;
  draftPayloadFields: Record<number, string>;
  setDraftPayloadFields: (update: (current: Record<number, string>) => Record<number, string>) => void;
  updateApproval: (requestId: number, status: "approved" | "rejected") => Promise<void>;
  executeApproval: (requestId: number) => Promise<void>;
  savePayloadFields: (request: ApprovalRequest, fields: Record<string, string>) => Promise<void>;
  workflowFor: (request: ApprovalRequest) => { status: string } | undefined;
};

function ApprovalCard({
  request,
  busyId,
  canWrite,
  liveWritesReady,
  draftPayloadFields,
  setDraftPayloadFields,
  updateApproval,
  executeApproval,
  savePayloadFields,
  workflowFor
}: ApprovalCardProps) {
  const isHaloApproval = request.action_type.startsWith("halopsa.");
  const payloadText = draftPayloadFields[request.id] ?? fieldsToText(request.payload?.fields);
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
      {request.block_reason ? (
        <div className="blocked-reason">
          <AlertTriangle size={15} aria-hidden="true" />
          {request.block_reason}
        </div>
      ) : null}
      <div className="payload-grid">
        <div className="payload-preview">
          <h3><FileJson size={16} aria-hidden="true" />Payload Preview</h3>
          <pre>{formatPayload(request.payload)}</pre>
        </div>
        <label className="payload-editor">
          Draft Fields
          <textarea
            disabled={request.status !== "pending"}
            rows={6}
            value={payloadText}
            onChange={(event) => setDraftPayloadFields((current) => ({ ...current, [request.id]: event.target.value }))}
          />
        </label>
      </div>
      <div className="workflow-link">
        <Workflow size={15} aria-hidden="true" />
        {request.workflow_run_id ? (
          <span>
            Workflow run {request.workflow_run_id}
            {workflowFor(request) ? `: ${workflowFor(request)?.status}` : ""}
          </span>
        ) : <span>No workflow run linked</span>}
      </div>
      {canWrite ? (
        <div className="row-actions">
          <button
            className="icon-button"
            disabled={busyId === request.id || request.status !== "pending"}
            type="button"
            onClick={() => void savePayloadFields(request, parseFields(payloadText))}
          >
            <Save size={16} aria-hidden="true" />
            Save Fields
          </button>
          <button
            disabled={busyId === request.id || request.status !== "pending"}
            type="button"
            onClick={() => void updateApproval(request.id, "approved")}
          >
            <CheckCircle2 size={16} aria-hidden="true" />
            Approve
          </button>
          <button
            disabled={busyId === request.id || request.status !== "pending"}
            type="button"
            onClick={() => void updateApproval(request.id, "rejected")}
          >
            <XCircle size={16} aria-hidden="true" />
            Reject
          </button>
          <button
            disabled={busyId === request.id || request.status !== "approved" || !isHaloApproval || !liveWritesReady}
            type="button"
            onClick={() => void executeApproval(request.id)}
          >
            <PlayCircle size={16} aria-hidden="true" />
            Execute
          </button>
        </div>
      ) : null}
    </div>
  );
}
