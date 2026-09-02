import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiFetch } from "../api/client";
import {
  loadStoredApiToken,
  loadStoredSelectedClientId,
  persistApiToken,
  persistSelectedClientId
} from "../api/headers";
import type {
  ApprovalRequest,
  AuthRoleResponse,
  ClientDirectoryEntry,
  ConnectorHealth,
  ConnectorStatus,
  EntitlementResponse,
  EventDelivery,
  EventHistory,
  HaloReadResult,
  HaloTicket,
  AuthSessionResponse,
  HaloTicketsResponse,
  ReadinessStep,
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
const PSA_CONNECTOR_IDS = ["halopsa", "connectwise", "servicenow", "autotask"] as const;
const defaultWriteHealth: HaloReadResult = {
  status: "blocked",
  message: "Loading PSA write health.",
  count: 0
};

export type WriteHealthPosture = {
  label: string;
  tone: "neutral" | "warning" | "success";
  icon: "info" | "warning" | "success";
};

export function getWriteHealthPosture(
  status: string | null | undefined,
  resolved: boolean
): WriteHealthPosture {
  if (!resolved) {
    return { label: "Checking write status…", tone: "neutral", icon: "info" };
  }
  if (status === "ready") {
    return { label: "Live writes ready", tone: "success", icon: "success" };
  }
  if (status === "not_configured") {
    return { label: "No PSA write path configured", tone: "neutral", icon: "info" };
  }
  if (status === "failed") {
    return { label: "Write path error", tone: "warning", icon: "warning" };
  }
  if (status === "blocked") {
    return { label: "Safe Mode · writes disabled", tone: "neutral", icon: "info" };
  }
  return { label: "Write path error", tone: "warning", icon: "warning" };
}

export type CapabilityGrantView = {
  capability_key: string;
  client_id: string | null;
};

export type AuthState = "demo" | "authenticated" | "invalid-token";

type AuthRefreshResult = {
  authState: AuthState | null;
  role: AuthRoleResponse["role"] | null;
};

type EffectiveCapabilityResponse = {
  principal_id: string | null;
  supported_capabilities: string[];
  grants: CapabilityGrantView[];
};

type DashboardContextValue = {
  actionTypes: string[];
  apiToken: string;
  principalId: string | null;
  authMethod: string;
  expiresAt: string | null;
  clientId: string;
  selectedClientId: string;
  clients: ClientDirectoryEntry[];
  commercialEntitlement: EntitlementResponse["commercial"];
  role: AuthRoleResponse["role"];
  isMspAdmin: boolean;
  endUserSupportEnabled: boolean;
  authState: AuthState | null;
  capabilityGrants: CapabilityGrantView[];
  capabilityResolved: boolean;
  capabilityError: string;
  connectors: ConnectorStatus[];
  haloConnector?: ConnectorStatus;
  huduConnector?: ConnectorStatus;
  writeHealth: HaloReadResult;
  writeHealthByConnector: Record<string, ConnectorHealth>;
  writeHealthResolved: boolean;
  liveWritesReady: boolean;
  haloTickets: HaloTicket[];
  approvalRequests: ApprovalRequest[];
  pendingApprovals: ApprovalRequest[];
  eventDeliveries: EventDelivery[];
  eventHistory: EventHistory[];
  workflowRuns: WorkflowRun[];
  refreshErrors: string[];
  statusMessage: string;
  setStatusMessage: (message: string) => void;
  loading: boolean;
  refreshNonce: number;
  roleResolved: boolean;
  clientScopeIds: string[] | null;
  hasClientScope: boolean;
  busyId: number | "draft" | null;
  selectedTicketId: string;
  canWrite: boolean;
  isAdmin: boolean;
  isConfigured: boolean;
  configurationLoading: boolean;
  configurationSteps: ReadinessStep[];
  setApiToken: (token: string) => void;
  setSelectedClientId: (clientId: string) => void;
  refresh: () => Promise<AuthRefreshResult | null>;
  refreshConfiguration: () => Promise<void>;
  saveApiToken: () => Promise<void>;
  clearApiToken: () => Promise<void>;
  logout: () => Promise<void>;
  selectTicket: (ticketId: string) => void;
  createDraft: (ticketId: string, actionType: string, fields: Record<string, string>) => Promise<void>;
  updateApproval: (requestId: number, status: "approved" | "rejected") => Promise<void>;
  executeApproval: (requestId: number, actionType: string) => Promise<void>;
  retryEventDelivery: (deliveryId: number) => Promise<void>;
  savePayloadFields: (request: ApprovalRequest, fields: Record<string, string>) => Promise<void>;
  workflowFor: (request: ApprovalRequest) => WorkflowRun | undefined;
};

export function executeEndpointFor(actionType: string): string | null {
  if (actionType.startsWith("halopsa.")) {
    return "/connectors/halopsa/approval-requests/{id}/execute";
  }
  if (actionType.startsWith("connectwise.")) {
    return "/connectors/connectwise/approval-requests/{id}/execute";
  }
  if (actionType.startsWith("teams.")) {
    return "/connectors/m365/teams/approval-requests/{id}/execute";
  }
  if (actionType.startsWith("m365.")) {
    return "/connectors/m365/approval-requests/{id}/execute";
  }
  if (actionType === "power_platform.solution_stage") {
    return "/consultant/solutions/deployment-approvals/{id}/execute";
  }
  if (actionType === "power_platform.solution_rollback") {
    return "/consultant/solutions/rollback-approvals/{id}/execute";
  }
  return null;
}

const DashboardContext = createContext<DashboardContextValue | undefined>(undefined);

export function DashboardProvider({ children, activePath = "" }: { children: ReactNode; activePath?: string }) {
  const [apiToken, setApiToken] = useState(() => loadStoredApiToken());
  const [role, setRole] = useState<AuthRoleResponse["role"]>("viewer");
  const [isMspAdmin, setIsMspAdmin] = useState(false);
  const [endUserSupportEnabled, setEndUserSupportEnabled] = useState(false);
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const [principalId, setPrincipalId] = useState<string | null>(null);
  const [authMethod, setAuthMethod] = useState("bearer");
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");
  const [selectedClientId, setSelectedClientIdState] = useState(() => loadStoredSelectedClientId());
  const [clients, setClients] = useState<ClientDirectoryEntry[]>([]);
  const [commercialEntitlement, setCommercialEntitlement] = useState<EntitlementResponse["commercial"]>(null);
  const [roleResolved, setRoleResolved] = useState(false);
  const [capabilityGrants, setCapabilityGrants] = useState<CapabilityGrantView[]>([]);
  const [capabilityResolved, setCapabilityResolved] = useState(false);
  const [capabilityError, setCapabilityError] = useState("");
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [writeHealth, setWriteHealth] = useState<HaloReadResult>(defaultWriteHealth);
  const [writeHealthByConnector, setWriteHealthByConnector] = useState<Record<string, ConnectorHealth>>({});
  const [writeHealthResolved, setWriteHealthResolved] = useState(false);
  const [clientScopeIds, setClientScopeIds] = useState<string[] | null>(null);
  const [haloTickets, setHaloTickets] = useState<HaloTicket[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequest[]>([]);
  const [eventDeliveries, setEventDeliveries] = useState<EventDelivery[]>([]);
  const [eventHistory, setEventHistory] = useState<EventHistory[]>([]);
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRun[]>([]);
  const [selectedTicketId, setSelectedTicketId] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [refreshErrors, setRefreshErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [busyId, setBusyId] = useState<number | "draft" | null>(null);
  const selectedTicketIdRef = useRef(selectedTicketId);
  const roleRequestIdRef = useRef(0);
  const activePathRef = useRef(activePath);
  const configuration = useConfiguredState({ role });

  useEffect(() => {
    selectedTicketIdRef.current = selectedTicketId;
  }, [selectedTicketId]);

  useEffect(() => {
    activePathRef.current = activePath;
  }, [activePath]);

  const setSelectedClientId = useCallback((nextClientId: string) => {
    const normalized = nextClientId.trim();
    setSelectedClientIdState(normalized);
    persistSelectedClientId(normalized);
  }, []);

  const refresh = useCallback(async (): Promise<AuthRefreshResult | null> => {
    setRefreshNonce((nonce) => nonce + 1);
    const roleRequestId = ++roleRequestIdRef.current;
    setLoading(true);
    setRole("viewer");
    setIsMspAdmin(false);
    setEndUserSupportEnabled(false);
    setAuthState(null);
    setPrincipalId(null);
    setAuthMethod("bearer");
    setExpiresAt(null);
    setRoleResolved(false);
    setCapabilityGrants([]);
    setCapabilityResolved(false);
    setCapabilityError("");
    setCommercialEntitlement(null);
    setClientScopeIds(null);
    setWriteHealthByConnector({});
    setWriteHealthResolved(false);
    try {
      let auth: AuthRoleResponse;
      let session: AuthSessionResponse | null = null;
      try {
        session = await apiFetch<AuthSessionResponse>("/auth/session");
      } catch {
        // Older appliances and transient probe failures retain bearer fallback.
      }
      if (session?.authenticated === true && session.auth_method && session.auth_method !== "bearer") {
        persistApiToken("");
        setApiToken("");
        auth = session;
      } else {
        auth = await apiFetch<AuthRoleResponse>("/auth/role");
      }
      if (roleRequestId !== roleRequestIdRef.current) {
        return null;
      }
      const results = await Promise.allSettled([
        apiFetch<ConnectorStatus[]>("/connectors"),
        activePathRef.current === "/tickets"
          ? apiFetch<HaloTicketsResponse>("/connectors/halopsa/tickets")
          : Promise.resolve<HaloTicketsResponse>({
            result: { status: "blocked", message: "Tickets are loaded on the Tickets screen.", count: 0 },
            items: []
          }),
        apiFetch<ApprovalRequest[]>("/approval-requests"),
        apiFetch<EventDelivery[]>("/automation/event-deliveries"),
        apiFetch<EventHistory[]>("/event-history"),
        apiFetch<WorkflowRun[]>("/workflow-runs"),
        apiFetch<ClientDirectoryEntry[]>("/clients"),
        apiFetch<EffectiveCapabilityResponse>("/packs/microsoft-admin/access/effective"),
        apiFetch<EntitlementResponse>("/entitlement")
      ]);
      const errors = results
        .slice(0, 7)
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .map((result) => result.reason instanceof Error ? result.reason.message : "Dashboard data unavailable.");
      const connectorRows = settledValue(results[0] as PromiseSettledResult<ConnectorStatus[]>, []);
      const configuredPsaConnectors = connectorRows.filter((connector) =>
        PSA_CONNECTOR_IDS.includes(connector.id as typeof PSA_CONNECTOR_IDS[number])
        && connector.status !== "not_configured"
      );
      const writeHealthResults = await Promise.allSettled(
        configuredPsaConnectors.map((connector) =>
          apiFetch<ConnectorHealth>(`/connectors/${encodeURIComponent(connector.id)}/write-health`)
        )
      );
      const nextWriteHealthByConnector = Object.fromEntries(
        configuredPsaConnectors.map((connector, index) => {
          const result = writeHealthResults[index];
          return [connector.id, result.status === "fulfilled" ? result.value : {
            status: "failed",
            message: "Unable to verify this PSA write path.",
            count: 0
          }];
        })
      );
      const firstWriteHealth = nextWriteHealthByConnector[configuredPsaConnectors[0]?.id ?? ""];
      const writeState: HaloReadResult = {
        status: firstWriteHealth?.status ?? "not_configured",
        message: firstWriteHealth?.message ?? "No PSA connector is configured.",
        count: firstWriteHealth?.count ?? 0
      };
      const ticketResponse = settledValue(results[1] as PromiseSettledResult<HaloTicketsResponse>, {
        result: { status: "blocked", message: "Tickets unavailable.", count: 0 },
        items: []
      });
      const clientRows = settledValue(results[6] as PromiseSettledResult<ClientDirectoryEntry[]>, []);
      const capabilityResult = results[7] as PromiseSettledResult<EffectiveCapabilityResponse>;
      const entitlementResult = results[8] as PromiseSettledResult<EntitlementResponse>;

      if (roleRequestId !== roleRequestIdRef.current) {
        return null;
      }
      const nextAuthState = deriveAuthState(auth, loadStoredApiToken());
      setRole(auth.role);
      setIsMspAdmin(auth.is_msp_admin === true);
      setClientScopeIds(Array.isArray(auth.client_ids)
        ? auth.client_ids.filter((clientId): clientId is string => typeof clientId === "string" && clientId.trim().length > 0)
        : typeof auth.client_id === "string" && auth.client_id.trim()
          ? [auth.client_id.trim()]
          : null);
      setEndUserSupportEnabled(auth.end_user_support_enabled === true);
      setAuthState(nextAuthState);
      setPrincipalId(auth.principal_id ?? null);
      setAuthMethod(auth.auth_method ?? (auth.demo_mode ? "demo" : "bearer"));
      setExpiresAt(auth.expires_at ?? null);
      setClientId(auth.client_id ?? "");
      setRoleResolved(true);
      if (capabilityResult.status === "fulfilled") {
        setCapabilityGrants(Array.isArray(capabilityResult.value?.grants) ? capabilityResult.value.grants : []);
        setCapabilityError("");
      } else {
        setCapabilityGrants([]);
        setCapabilityError(
          capabilityResult.reason instanceof Error
            ? capabilityResult.reason.message
            : "Microsoft Admin access could not be verified."
        );
      }
      setCapabilityResolved(true);
      if (entitlementResult.status === "fulfilled" && entitlementResult.value?.commercial !== undefined) {
        setCommercialEntitlement(
          entitlementResult.value.commercial !== null &&
          typeof entitlementResult.value.commercial === "object" &&
          !Array.isArray(entitlementResult.value.commercial)
            ? entitlementResult.value.commercial
            : null
        );
      } else {
        setCommercialEntitlement(null);
      }
      setConnectors(asArray(connectorRows));
      setWriteHealthByConnector(nextWriteHealthByConnector);
      setWriteHealth(writeState);
      setWriteHealthResolved(true);
      setHaloTickets(asArray(ticketResponse.items));
      setApprovalRequests(asArray(settledValue(results[2] as PromiseSettledResult<ApprovalRequest[]>, [])));
      setEventDeliveries(asArray(settledValue(results[3] as PromiseSettledResult<EventDelivery[]>, [])));
      setEventHistory(asArray(settledValue(results[4] as PromiseSettledResult<EventHistory[]>, [])));
      setWorkflowRuns(asArray(settledValue(results[5] as PromiseSettledResult<WorkflowRun[]>, [])));
      setClients(asArray<ClientDirectoryEntry>(clientRows).filter((client) => client.client_id !== "__quarantine__"));
      setRefreshErrors(errors);
      await configuration.refresh();
      if (!selectedTicketIdRef.current && ticketResponse.items[0]) {
        setSelectedTicketId(ticketResponse.items[0].id);
      }
      return { authState: nextAuthState, role: auth.role };
    } catch (error) {
      if (roleRequestId !== roleRequestIdRef.current) {
        return null;
      }
      setRole("viewer");
      setIsMspAdmin(false);
      setEndUserSupportEnabled(false);
      setRoleResolved(false);
      setPrincipalId(null);
      setAuthMethod("bearer");
      setExpiresAt(null);
      const nextAuthState = hasStoredApiToken() && isUnauthorized(error) ? "invalid-token" : null;
      setAuthState(nextAuthState);
      setCapabilityGrants([]);
      setCapabilityResolved(false);
      setCapabilityError("");
      setCommercialEntitlement(null);
      setClientScopeIds(null);
      setWriteHealthByConnector({});
      setStatusMessage(error instanceof Error ? error.message : "Unable to refresh dashboard.");
      return { authState: nextAuthState, role: null };
    } finally {
      if (roleRequestId === roleRequestIdRef.current) {
        setLoading(false);
      }
    }
  }, [configuration.refresh]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const saveApiToken = useCallback(async () => {
    persistApiToken(apiToken);
    const result = await refresh();
    if (result?.authState === "invalid-token") {
      setStatusMessage("Access credential rejected. Return to sign in and try again.");
      return;
    }
    if (result?.role) {
      setStatusMessage(`API token saved. Access resolved as ${result.role}.`);
      return;
    }
    setStatusMessage("API token saved for dashboard requests.");
  }, [apiToken, refresh]);

  const clearApiToken = useCallback(async () => {
    setApiToken("");
    persistApiToken("");
    setStatusMessage("API token cleared.");
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await apiFetch<{ authenticated: boolean }>("/auth/logout", { method: "POST" });
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Sign out failed.");
      return;
    }
    setApiToken("");
    persistApiToken("");
    setStatusMessage("Signed out.");
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

  const executeApproval = useCallback(async (requestId: number, actionType: string) => {
    const endpoint = executeEndpointFor(actionType);
    if (endpoint === null) {
      setStatusMessage("This approval type has no live execute endpoint.");
      return;
    }
    setBusyId(requestId);
    try {
      const approval = await apiFetch<ApprovalRequest>(
        endpoint.replace("{id}", String(requestId)),
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

  const retryEventDelivery = useCallback(async (deliveryId: number) => {
    try {
      const result = await apiFetch<{ delivery: EventDelivery }>(`/automation/event-deliveries/${deliveryId}/retry`, {
        method: "POST"
      });
      setStatusMessage(`Event delivery ${deliveryId} ${result.delivery.status}.`);
      await refresh();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Event delivery retry failed.");
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
      principalId: (authState && roleResolved) ? principalId : null,
      authMethod,
      expiresAt,
      clientId,
      selectedClientId,
      clients,
      commercialEntitlement,
      role,
      isMspAdmin,
      endUserSupportEnabled,
      authState,
      capabilityGrants,
      capabilityResolved,
      capabilityError,
      connectors,
      haloConnector,
      huduConnector,
      writeHealth,
      writeHealthByConnector,
      writeHealthResolved,
      liveWritesReady: connectors.some((connector) =>
        PSA_CONNECTOR_IDS.includes(connector.id as typeof PSA_CONNECTOR_IDS[number])
        && connector.status !== "not_configured"
      ) && connectors
        .filter((connector) =>
          PSA_CONNECTOR_IDS.includes(connector.id as typeof PSA_CONNECTOR_IDS[number])
          && connector.status !== "not_configured"
        )
        .every((connector) => writeHealthByConnector[connector.id]?.status === "ready"),
      haloTickets,
      approvalRequests,
      pendingApprovals: approvalRequests.filter((request) => request.status === "pending"),
      eventDeliveries,
      eventHistory,
      workflowRuns,
      refreshErrors,
      statusMessage,
      setStatusMessage,
      loading,
      refreshNonce,
      roleResolved,
      clientScopeIds,
      hasClientScope: clientScopeIds !== null && clientScopeIds.length > 0,
      busyId,
      selectedTicketId,
      canWrite: roleResolved && role !== "viewer",
      isAdmin: roleResolved && role === "admin",
      isConfigured: configuration.isConfigured,
      configurationLoading: configuration.loading,
      configurationSteps: configuration.steps,
      setApiToken,
      setSelectedClientId,
      refresh,
      refreshConfiguration: configuration.refresh,
      saveApiToken,
      clearApiToken,
      logout,
      selectTicket,
      createDraft,
      updateApproval,
      executeApproval,
      retryEventDelivery,
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
    authMethod,
    expiresAt,
    principalId,
    authState,
    clientId,
    clients,
    commercialEntitlement,
    approvalRequests,
    busyId,
    capabilityError,
    capabilityGrants,
    capabilityResolved,
    clearApiToken,
    logout,
    configuration.isConfigured,
    configuration.loading,
    configuration.steps,
    configuration.refresh,
    connectors,
    createDraft,
    eventHistory,
    executeApproval,
    eventDeliveries,
    endUserSupportEnabled,
    haloTickets,
    loading,
    refreshNonce,
    roleResolved,
    refresh,
    refreshErrors,
    retryEventDelivery,
    role,
    saveApiToken,
    savePayloadFields,
    selectTicket,
    selectedClientId,
    selectedTicketId,
    setSelectedClientId,
    statusMessage,
    updateApproval,
    workflowRuns,
    writeHealth,
    writeHealthByConnector,
    writeHealthResolved
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

function hasStoredApiToken(): boolean {
  return loadStoredApiToken().trim().length > 0;
}

function isUnauthorized(error: unknown): boolean {
  return typeof error === "object"
    && error !== null
    && "status" in error
    && error.status === 401;
}

function deriveAuthState(auth: AuthRoleResponse, storedToken: string): AuthState | null {
  if (auth.demo_mode === true) {
    return "demo";
  }
  if (auth.auth_method && auth.auth_method !== "bearer") {
    return "authenticated";
  }
  return storedToken.trim() ? "authenticated" : null;
}

export { defaultFieldText };
