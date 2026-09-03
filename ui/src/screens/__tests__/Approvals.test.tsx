import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Approvals } from "../Approvals";
import { useDashboard } from "../../app/DashboardContext";
import type { ApprovalRequest } from "../../api/types";

vi.mock("../../app/DashboardContext", async () => {
  const actual = await vi.importActual<typeof import("../../app/DashboardContext")>("../../app/DashboardContext");
  return { ...actual, useDashboard: vi.fn() };
});

const mockedUseDashboard = vi.mocked(useDashboard);

function approval(overrides: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    id: 1,
    subject_id: "subject-1",
    action_type: "m365.user.disable",
    status: "approved",
    comment: "",
    execution_status: "not_started",
    execution_message: "",
    can_execute: true,
    client_id: "acme",
    ...overrides
  };
}

function renderApproval(
  request: ReturnType<typeof approval>,
  options: { canWrite?: boolean; canWriteExternally?: boolean; liveWritesReady?: boolean; isAdmin?: boolean } = {}
) {
  const executeApproval = vi.fn().mockResolvedValue(undefined);
  const refresh = vi.fn().mockResolvedValue(undefined);
  mockedUseDashboard.mockReturnValue({
    approvalRequests: [request],
    pendingApprovals: [],
    canWrite: options.canWrite ?? true,
    canWriteExternally: options.canWriteExternally ?? options.canWrite ?? true,
    isAdmin: options.isAdmin ?? true,
    busyId: null,
    updateApproval: vi.fn(),
    executeApproval,
    savePayloadFields: vi.fn(),
    workflowFor: () => undefined,
    refresh,
    liveWritesReady: options.liveWritesReady ?? false,
    selectedClientId: "acme",
    isMspAdmin: false
  } as never);

  render(<MemoryRouter><Approvals /></MemoryRouter>);
  return {
    executeButton: screen.getByRole("button", { name: "Execute" }),
    executeApproval,
    refresh
  };
}

describe("Approvals execute button", () => {
  beforeEach(() => {
    mockedUseDashboard.mockReset();
    vi.unstubAllGlobals();
  });

  it("distinguishes a pending approval fetch from an empty queue", () => {
    const dashboard = {
      approvalRequests: [],
      pendingApprovals: [],
      canWrite: false,
      isAdmin: false,
      busyId: null,
      updateApproval: vi.fn(),
      executeApproval: vi.fn(),
      savePayloadFields: vi.fn(),
      workflowFor: () => undefined,
      refresh: vi.fn(),
      loading: true
    };
    mockedUseDashboard.mockReturnValue(dashboard as never);
    const view = render(<Approvals />);

    expect(screen.getByText("Loading approval requests…")).toBeInTheDocument();

    mockedUseDashboard.mockReturnValue({ ...dashboard, loading: false } as never);
    view.rerender(<Approvals />);

    expect(screen.getByText("No approval requests yet.")).toBeInTheDocument();
    expect(screen.getByText("Approval requests appear here when a governed action needs review.")).toBeInTheDocument();
  });

  it.each(["m365.user.disable", "teams.message.send"])(
    "enables %s when approved and executable even if Halo writes are not ready",
    (actionType) => {
      expect(renderApproval(approval({ action_type: actionType })).executeButton).toBeEnabled();
    }
  );

  it.each([
    ["connectwise.x", false, "approved"],
    ["m365.user.disable", true, "pending"]
  ])("disables %s when the approval cannot be explicitly executed", (actionType, canExecute, status) => {
    expect(renderApproval(approval({ action_type: actionType, can_execute: canExecute, status })).executeButton).toBeDisabled();
  });

  it("explains why an unmapped action has no manual execute button", () => {
    mockedUseDashboard.mockReturnValue({
      approvalRequests: [approval({ action_type: "smart_action:foo" })],
      pendingApprovals: [],
      canWrite: true,
      isAdmin: true,
      busyId: null,
      updateApproval: vi.fn(),
      executeApproval: vi.fn(),
      savePayloadFields: vi.fn(),
      workflowFor: () => undefined,
      refresh: vi.fn(),
      liveWritesReady: false
    } as never);
    render(<MemoryRouter><Approvals /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Execute" })).not.toBeInTheDocument();
    expect(screen.getByText("Executed from its own workflow after approval — no manual execute here.")).toBeInTheDocument();
  });

  it("explains the technician requirement for mapped execute actions", () => {
    const { executeButton } = renderApproval(approval(), { canWrite: false });

    expect(executeButton).toBeDisabled();
    expect(executeButton).toHaveAttribute("title", "Requires technician access");
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("explains HaloPSA Safe Mode when it gates an approved execution", () => {
    const { executeButton } = renderApproval(
      approval({ action_type: "halopsa.add_note", can_execute: false }),
      { liveWritesReady: false }
    );

    expect(executeButton).toBeDisabled();
    expect(executeButton).toHaveAttribute("title", "Ticketing write check failed");
    expect(screen.getAllByText("Ticketing write check failed")).toHaveLength(1);
  });

  it("keeps external execution disabled while local approval controls remain available", () => {
    const { executeButton } = renderApproval(approval({ status: "pending" }), { canWriteExternally: false });

    expect(executeButton).toBeDisabled();
    expect(executeButton).toHaveAttribute("title", "Live writes are off on this appliance");
    expect(screen.getByText("Live writes are off on this appliance")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("renders the backend block reason for Power Platform approvals", () => {
    const reason = "Power Platform deployment is blocked until WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true.";
    const { executeButton } = renderApproval(approval({
      action_type: "power_platform.solution_stage",
      can_execute: false,
      block_reason: reason
    }));

    expect(executeButton).toBeDisabled();
    expect(executeButton).toHaveAttribute("title", reason);
    expect(screen.getAllByText(reason)).toHaveLength(2);
    expect(screen.queryByText("Executed from its own workflow after approval — no manual execute here.")).not.toBeInTheDocument();
  });

  it("enables approved Microsoft runbooks only for administrators", () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook", can_execute: false });
    expect(renderApproval(request, { isAdmin: true }).executeButton).toBeEnabled();
  });

  it("keeps digest-bound Microsoft runbook plans immutable", () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook", can_execute: false });
    renderApproval(request, { isAdmin: true });

    expect(screen.getByText("Digest-bound plan")).toBeInTheDocument();
    expect(screen.getByText(/Runbook parameters cannot be edited/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Draft Fields")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save Fields" })).not.toBeInTheDocument();
  });

  it("keeps Microsoft runbook execution disabled for technicians", () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook", can_execute: false });
    expect(renderApproval(request, { isAdmin: false }).executeButton).toBeDisabled();
    expect(screen.getByText("Admin runbook execution requires administrator access.")).toBeInTheDocument();
  });

  it("does not allow a Microsoft runbook approval to be replayed", () => {
    const request = approval({
      action_type: "microsoft_admin.powershell_runbook",
      execution_status: "succeeded",
      can_execute: false
    });
    expect(renderApproval(request, { isAdmin: true }).executeButton).toBeDisabled();
  });

  it("executes a Microsoft runbook through the pack endpoint and refreshes the queue", async () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook", id: 42, can_execute: false });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      approval: { ...request, execution_status: "succeeded" },
      result: { status: "succeeded", message: "PowerShell runbook completed." }
    }), { status: 200 })));
    const { executeButton, executeApproval, refresh } = renderApproval(request, { isAdmin: true });

    fireEvent.click(executeButton);

    expect(await screen.findByRole("status")).toHaveTextContent("PowerShell runbook completed.");
    expect(fetch).toHaveBeenCalledWith(
      "/packs/microsoft-admin/runbooks/approvals/42/execute",
      expect.objectContaining({ method: "POST" })
    );
    expect(executeApproval).not.toHaveBeenCalled();
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("shows a bounded execution error without refreshing", async () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook", id: 42, can_execute: false });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "PowerShell runtime is unavailable."
    }), { status: 409 })));
    const { executeButton, refresh } = renderApproval(request, { isAdmin: true });

    fireEvent.click(executeButton);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That action conflicts with the appliance's current state. Refresh and try again."
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("links executed approvals to their run and filtered audit subject", () => {
    const request = approval({
      execution_status: "succeeded",
      executed_at: "2026-08-31T01:01:00Z",
      execution_id: 88
    });
    renderApproval(request);

    expect(screen.getByRole("link", { name: "Open run #88" })).toHaveAttribute("href", "/executions/88?kind=execution");
    expect(screen.getByRole("link", { name: "View Audit" })).toHaveAttribute("href", "/audit?subject=subject-1");
  });

  it("falls back to the audit subject when the API has no execution record id", () => {
    renderApproval(approval({ execution_status: "succeeded", executed_at: "2026-08-31T01:01:00Z" }));

    expect(screen.getByText("Recorded in Audit · subject-1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Audit" })).toHaveAttribute("href", "/audit?subject=subject-1");
  });

  it("explains why a pending approval is awaiting execution", () => {
    renderApproval(approval({ status: "pending", execution_status: "not_started" }));

    expect(screen.getByText("Awaiting execution")).toBeInTheDocument();
    expect(screen.getByText("Approval must be approved before execution.")).toBeInTheDocument();
  });
});
