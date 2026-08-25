import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    execution_status: "pending",
    execution_message: "",
    can_execute: true,
    ...overrides
  };
}

function renderApproval(
  request: ReturnType<typeof approval>,
  options: { liveWritesReady?: boolean; isAdmin?: boolean } = {}
) {
  const executeApproval = vi.fn().mockResolvedValue(undefined);
  const refresh = vi.fn().mockResolvedValue(undefined);
  mockedUseDashboard.mockReturnValue({
    approvalRequests: [request],
    pendingApprovals: [],
    canWrite: true,
    isAdmin: options.isAdmin ?? true,
    busyId: null,
    updateApproval: vi.fn(),
    executeApproval,
    savePayloadFields: vi.fn(),
    workflowFor: () => undefined,
    refresh,
    liveWritesReady: options.liveWritesReady ?? false
  } as never);

  render(<Approvals />);
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

  it.each(["m365.user.disable", "teams.message.send"])(
    "enables %s when approved and executable even if Halo writes are not ready",
    (actionType) => {
      expect(renderApproval(approval({ action_type: actionType })).executeButton).toBeEnabled();
    }
  );

  it.each([
    ["connectwise.x", false, "approved"],
    ["smart_action:foo", true, "approved"],
    ["m365.user.disable", true, "pending"]
  ])("disables %s when the approval cannot be explicitly executed", (actionType, canExecute, status) => {
    expect(renderApproval(approval({ action_type: actionType, can_execute: canExecute, status })).executeButton).toBeDisabled();
  });

  it("enables approved Microsoft runbooks only for administrators", () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook" });
    expect(renderApproval(request, { isAdmin: true }).executeButton).toBeEnabled();
  });

  it("keeps Microsoft runbook execution disabled for technicians", () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook" });
    expect(renderApproval(request, { isAdmin: false }).executeButton).toBeDisabled();
    expect(screen.getByText("PowerShell runbook execution requires administrator access.")).toBeInTheDocument();
  });

  it("executes a Microsoft runbook through the pack endpoint and refreshes the queue", async () => {
    const request = approval({ action_type: "microsoft_admin.powershell_runbook", id: 42 });
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
    const request = approval({ action_type: "microsoft_admin.powershell_runbook", id: 42 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "PowerShell runtime is unavailable."
    }), { status: 409 })));
    const { executeButton, refresh } = renderApproval(request, { isAdmin: true });

    fireEvent.click(executeButton);

    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete this request");
    expect(refresh).not.toHaveBeenCalled();
  });
});
