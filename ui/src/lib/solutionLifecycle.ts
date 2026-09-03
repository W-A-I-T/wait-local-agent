export type SolutionLifecycleStage = "draft" | "reviewed" | "approval-needed" | "materialized" | "deployed" | "review-only";

export type SolutionLifecycleInput = {
  package_status?: unknown;
  deployable?: unknown;
  execution_started?: unknown;
  deployment_started?: unknown;
  approval_status?: unknown;
  approval_required?: unknown;
  materialized?: unknown;
  readiness?: unknown;
};

export type SolutionLifecycle = { stage: SolutionLifecycleStage; label: string; index: number };

export const SOLUTION_LIFECYCLE_STAGES: Array<{ stage: Exclude<SolutionLifecycleStage, "review-only">; label: string }> = [
  { stage: "draft", label: "Draft" },
  { stage: "reviewed", label: "Reviewed" },
  { stage: "approval-needed", label: "Approval needed" },
  { stage: "materialized", label: "Materialized" },
  { stage: "deployed", label: "Deployed" },
];

export function solutionLifecycle(input: SolutionLifecycleInput | null | undefined): SolutionLifecycle {
  const value = input ?? {};
  const packageStatus = text(value.package_status).toLowerCase();
  const approvalStatus = text(value.approval_status).toLowerCase();
  if (value.deployable === false || packageStatus === "review_only") return { stage: "review-only", label: "Review-only", index: -1 };
  if (value.deployment_started === true) return lifecycleAt("deployed");
  if (value.materialized === true || value.execution_started === true || ["materialized", "materialized_source"].includes(packageStatus)) return lifecycleAt("materialized");
  const approvalComplete = ["approved", "succeeded", "completed"].includes(approvalStatus);
  if ((!approvalComplete && value.approval_required === true) || ["pending", "needs_approval", "approval_needed", "requested", "awaiting_approval"].includes(approvalStatus)) return lifecycleAt("approval-needed");
  if (value.deployable === true || ["deployable_source", "partial_source", "reviewed", "ready"].includes(packageStatus) || value.readiness === "ready") return lifecycleAt("reviewed");
  return lifecycleAt("draft");
}

function lifecycleAt(stage: Exclude<SolutionLifecycleStage, "review-only">): SolutionLifecycle {
  const index = SOLUTION_LIFECYCLE_STAGES.findIndex((item) => item.stage === stage);
  return { ...SOLUTION_LIFECYCLE_STAGES[index], index };
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}
