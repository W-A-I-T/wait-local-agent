import { describe, expect, it } from "vitest";
import { solutionLifecycle } from "./solutionLifecycle";

describe("solution lifecycle", () => {
  it.each([
    [{}, "draft"],
    [{ package_status: "deployable_source", deployable: true }, "reviewed"],
    [{ package_status: "partial_source", deployable: true, approval_required: true }, "approval-needed"],
    [{ package_status: "partial_source", deployable: true, approval_required: true, approval_status: "approved" }, "reviewed"],
    [{ package_status: "deployable_source", deployable: true, execution_started: true }, "materialized"],
    [{ package_status: "deployable_source", deployable: true, deployment_started: true }, "deployed"],
    [{ package_status: "review_only", deployable: false }, "review-only"],
  ])("maps backend state %#", (input, expected) => {
    expect(solutionLifecycle(input).stage).toBe(expected);
  });
});
