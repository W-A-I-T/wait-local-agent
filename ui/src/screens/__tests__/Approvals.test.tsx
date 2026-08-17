import { render, screen } from "@testing-library/react";
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

function renderApproval(request: ReturnType<typeof approval>, liveWritesReady = false) {
  mockedUseDashboard.mockReturnValue({
    approvalRequests: [request],
    pendingApprovals: [],
    canWrite: true,
    busyId: null,
    updateApproval: vi.fn(),
    executeApproval: vi.fn(),
    savePayloadFields: vi.fn(),
    workflowFor: () => undefined,
    liveWritesReady
  } as never);

  render(<Approvals />);
  return screen.getByRole("button", { name: "Execute" });
}

describe("Approvals execute button", () => {
  beforeEach(() => {
    mockedUseDashboard.mockReset();
  });

  it.each(["m365.user.disable", "teams.message.send"])(
    "enables %s when approved and executable even if Halo writes are not ready",
    (actionType) => {
      expect(renderApproval(approval({ action_type: actionType }))).toBeEnabled();
    }
  );

  it.each([
    ["connectwise.x", false, "approved"],
    ["smart_action:foo", true, "approved"],
    ["m365.user.disable", true, "pending"]
  ])("disables %s when the approval cannot be explicitly executed", (actionType, canExecute, status) => {
    expect(renderApproval(approval({ action_type: actionType, can_execute: canExecute, status }))).toBeDisabled();
  });
});
