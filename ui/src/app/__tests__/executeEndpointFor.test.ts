import { describe, expect, it } from "vitest";
import { executeEndpointFor } from "../DashboardContext";

describe("executeEndpointFor", () => {
  it.each([
    ["halopsa.ticket.note", "/connectors/halopsa/approval-requests/{id}/execute"],
    ["connectwise.x", "/connectors/connectwise/approval-requests/{id}/execute"],
    ["teams.message.send", "/connectors/m365/teams/approval-requests/{id}/execute"],
    ["m365.user.disable", "/connectors/m365/approval-requests/{id}/execute"],
    ["power_platform.solution_stage", "/consultant/solutions/deployment-approvals/{id}/execute"],
    ["power_platform.solution_rollback", "/consultant/solutions/rollback-approvals/{id}/execute"]
  ])("maps %s to its provider execute endpoint", (actionType, endpoint) => {
    expect(executeEndpointFor(actionType)).toBe(endpoint);
  });

  it.each(["smart_action:foo"])(
    "returns null for unmapped action type %s",
    (actionType) => {
      expect(executeEndpointFor(actionType)).toBeNull();
    }
  );
});
