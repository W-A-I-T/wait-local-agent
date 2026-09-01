export type HandoffArtifact = Record<string, unknown>;

export type SolutionDeliveryHandoff = {
  source: "solutions-architect";
  clientId: string;
  artifacts: HandoffArtifact[];
};

export const SOLUTION_DELIVERY_ROUTE = "/consultant/solution-delivery";

function isPlainObject(value: unknown): value is HandoffArtifact {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function collectHandoffArtifacts(
  powerAppsArtifact: unknown,
  flowPlan: unknown,
): HandoffArtifact[] {
  return [powerAppsArtifact, flowPlan].filter(isPlainObject);
}

export function readSolutionDeliveryHandoff(state: unknown): SolutionDeliveryHandoff | null {
  if (!isPlainObject(state) || state.source !== "solutions-architect" || typeof state.clientId !== "string") {
    return null;
  }
  if (!Array.isArray(state.artifacts) || state.artifacts.length === 0 || !state.artifacts.every(isPlainObject)) {
    return null;
  }
  return {
    source: "solutions-architect",
    clientId: state.clientId,
    artifacts: state.artifacts,
  };
}
