import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiFetch } from "../api/client";
import {
  loadStoredApiToken,
  persistApiToken
} from "../api/headers";
import type {
  ApprovalRequest,
  AuthRoleResponse,
  ConnectorStatus,
  EventHistory,
  HaloReadResult,
  HaloTicket,
  HaloTicketsResponse,
  WorkflowRun
} from "../api/types";
import { useConfiguredState } from "../hooks/useConfiguredState";

const actionTypes = [
  "add_note",
  "draft_response",
  "update_status",
  "assign_technician",
  "update_ticket_fields"
];

const defaultFieldText = "note=Reviewed by WAIT Local Agent";
const defaultWriteHealth: HaloReadResult = {
  status: "blocked",
  message: "Loading HaloPSA write health.",
  count: 0
};

type DashboardContextValue = {
  actionTypes: string[];
  apiToken: string;
  role: AuthRoleResponse["role"];
  connectors: ConnectorStatus[];
  haloConnector?: ConnectorStatus;
  huduConnector?: ConnectorStatus;
  writeHealth: HaloReadResult;
  liveWritesReady: boolean;
  haloTickets: HaloTicket[];
  approvalRequests: ApprovalRequest[];
  pendingApprovals: ApprovalRequest[];
  eventHistory: EventHistory[];
  workflowRuns: WorkflowRun[];
  refreshErrors: string[];
  statusMessage: string;
  loading: boolean;
  busyId: number | "draft" | null;
  selectedTicketId: string;
  canWrite: boolean;
  isAdmin: boolean;
  isConfigured: boolean;
  configurationLoading: boolean;
  setApiToken: (token: string) => void;
  refresh: () => Promise<void>;
  saveApiToken: () => Promise<void>;
  clearApiToken: () => Promise<void>;
  selectTicket: (ticketId: string) => void;
  createDraft: (ticketId: string, actionType: string, fields: Record<string, string>) => Promise<void>;
  updateApproval: (requestId: number, status: "approved" | "rejected") => Promise<void>;
  executeApproval: (requestId: number) => Promise<void>;
  savePayloadFields: (request: ApprovalRequest, fields: Record<string, string>) => Promise<void>;
  workflowFor: (request: ApprovalRequest) => WorkflowRun | undefined;
};

const DashboardContext = createContext<DashboardContextValue | undefined>(undefined);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [apiToken, setApiToken] = useState(() => loadStoredApiToken());
  const [role, setRole] = useState<AuthRoleResponse["role"]>("admin");
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [writeHealth, setWriteHealth] = useState<HaloReadResult>(defaultWriteHealth);
  const [haloTickets, setHaloTickets] = useState<HaloTicket[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequest[]>([]);
  const [eventHistory, setEventHistory] = useState<EventHistory[]>([]);
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRun[]>([]);
  const [selectedTicketId, setSelectedTicketId] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [refreshErrors, setRefreshErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | "draft" | null>(null);
  const selectedTicketIdRef = useRef(selectedTicketId);
  const configuration = useConfiguredState();

  useEffect(() => {
    selectedTicketIdRef.current = selectedTicketId;
  }, [selectedTicketId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const auth = await apiFetch<AuthRoleResponse>("/auth/role");
      const results = await Promise.allSettled([
        apiFetch<ConnectorStatus[]>("/connectors"),
        apiFetch<HaloReadResult>("/connectors/halopsa/write-health"),
        apiFetch<HaloTicketsResponse>("/connectors/halopsa/tickets"),
        apiFetch<ApprovalRequest[]>("/approval-requests"),
        apiFetch<EventHistory[]>("/event-history"),
        apiFetch<WorkflowRun[]>("/workflow-runs")
      ]);
      const errors = results
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .map((result) => result.reason instanceof Error ? result.reason.message : "Dashboard data unavailable.");
      const connectorRows = settledValue(results[0] as PromiseSettledResult<ConnectorStatus[]>, []);
      const writeState = settledValue(results[1] as PromiseSettledResult<HaloReadResult>, defaultWriteHealth);
      const ticketResponse = settledValue(results[2] as PromiseSettledResult<HaloTicketsResponse>, {
        result: { status: "blocked", message: "Tickets unavailable.", count: 0 },
        items: []
      });

      setRole(auth.role);
      setConnectors(asArray(connectorRows));
      setWriteHealth(writeState);
      setHaloTickets(asArray(ticketResponse.items));
      setApprovalRequests(asArray(settledValue(results[3] as PromiseSettledResult<ApprovalRequest[]>, [])));
      setEventHistory(asArray(settledValue(results[4] as PromiseSettledResult<EventHistory[]>, [])));
      setWorkflowRuns(asArray(settledValue(results[5] as PromiseSettledResult<WorkflowRun[]>, [])));
      setRefreshErrors(errors);
      if (!selectedTicketIdRef.current && ticketResponse.items[0]) {
        setSelectedTicketId(ticketResponse.items[0].id);
      }
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Unable to refresh dashboard.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const saveApiToken = useCallback(async () => {
    persistApiToken(apiToken);
    setStatusMessage("API token saved for dashboard requests.");
    await refresh();
  }, [apiToken, refresh]);

  const clearApiToken = useCallback(async () => {
    setApiToken("");
    persistApiToken("");
    setStatusMessage("API token cleared.");
    await refresh();
  }, [refresh]);

  const createDraft = useCallback(async (
    ticketId: string,
    selectedActionType: string,
    fields: Record<string, string>
  ) => {
    setBusyId("draft");
    try {
      const draft = await apiFetch<{ approval_request_id: number }>(
        `/connectors/halopsa/tickets/${encodeURIComponent(ticketId)}/drafts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action_type: selectedActionType, fields })
        }
      );
      setStatusMessage(`Draft created as approval request ${draft.approval_request_id}.`);
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Draft creation failed.");
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  const updateApproval = useCallback(async (requestId: number, status: "approved" | "rejected") => {
    setBusyId(requestId);
    try {
      const approval = await apiFetch<ApprovalRequest>(`/approval-requests/${requestId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          comment: status === "approved" ? "Approved from WAIT dashboard" : "Rejected from dashboard"
        })
      });
      setStatusMessage(`${approval.action_type} ${status}; execution ${approval.execution_status}.`);
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Approval update failed.");
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  const executeApproval = useCallback(async (requestId: number) => {
    setBusyId(requestId);
    try {
      const approval = await apiFetch<ApprovalRequest>(
        `/connectors/halopsa/approval-requests/${requestId}/execute`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({})
        }
      );
      setStatusMessage(`${approval.action_type} execution ${approval.execution_status}.`);
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Execution failed.");
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  const savePayloadFields = useCallback(async (request: ApprovalRequest, fields: Record<string, string>) => {
    setBusyId(request.id);
    try {
      await apiFetch<ApprovalRequest>(`/approval-requests/${request.id}/payload`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields })
      });
      setStatusMessage(`Approval request ${request.id} payload updated.`);
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Payload update failed.");
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  const selectTicket = useCallback((ticketId: string) => {
    setSelectedTicketId(ticketId);
  }, []);

  const value = useMemo<DashboardContextValue>(() => {
    const haloConnector = connectors.find((connector) => connector.id === "halopsa");
    const huduConnector = connectors.find((connector) => connector.id === "hudu");
    return {
      actionTypes,
      apiToken,
      role,
      connectors,
      haloConnector,
      huduConnector,
      writeHealth,
      liveWritesReady: writeHealth.status === "ready",
      haloTickets,
      approvalRequests,
      pendingApprovals: approvalRequests.filter((request) => request.status === "pending"),
      eventHistory,
      workflowRuns,
      refreshErrors,
      statusMessage,
      loading,
      busyId,
      selectedTicketId,
      canWrite: role !== "viewer",
      isAdmin: role === "admin",
      isConfigured: configuration.isConfigured,
      configurationLoading: configuration.loading,
      setApiToken,
      refresh,
      saveApiToken,
      clearApiToken,
      selectTicket,
      createDraft,
      updateApproval,
      executeApproval,
      savePayloadFields,
      workflowFor: (request) => {
        if (request.workflow_run_id === undefined || request.workflow_run_id === null) {
          return undefined;
        }
        return workflowRuns.find((run) => String(run.id) === String(request.workflow_run_id));
      }
    };
  }, [
    apiToken,
    approvalRequests,
    busyId,
    clearApiToken,
    configuration.isConfigured,
    configuration.loading,
    connectors,
    createDraft,
    eventHistory,
    executeApproval,
    haloTickets,
    loading,
    refresh,
    refreshErrors,
    role,
    saveApiToken,
    savePayloadFields,
    selectTicket,
    selectedTicketId,
    statusMessage,
    updateApproval,
    workflowRuns,
    writeHealth
  ]);

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard(): DashboardContextValue {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error("useDashboard must be used inside DashboardProvider");
  }
  return context;
}

function settledValue<T>(result: PromiseSettledResult<T>, fallback: T): T {
  return result.status === "fulfilled" ? result.value : fallback;
}

function asArray<T>(value: T[] | unknown): T[] {
  return Array.isArray(value) ? value : [];
}

export { defaultFieldText };
