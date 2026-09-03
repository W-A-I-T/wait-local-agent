export type HandoffArtifact = Record<string, unknown>;

export type SolutionDeliveryHandoffArtifact = {
  id: string;
  digest: string | null;
};

export type SolutionDeliveryHandoff = {
  source: "solutions-architect";
  clientId: string;
  artifacts: HandoffArtifact[];
  blueprint?: { id: string; name: string };
  artifactMetadata?: SolutionDeliveryHandoffArtifact[];
  generatedAt?: string;
};

export const SOLUTION_DELIVERY_ROUTE = "/consultant/solution-delivery";
export const SOLUTION_DELIVERY_HANDOFF_QUERY = "handoff";
const SOLUTION_DELIVERY_HANDOFF_STORAGE_PREFIX = "wait-local-agent:solution-delivery-handoff:";

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
  if (!isPlainObject(state) || state.source !== "solutions-architect" || typeof state.clientId !== "string" || !state.clientId.trim()) {
    return null;
  }
  if (!Array.isArray(state.artifacts) || state.artifacts.length === 0 || !state.artifacts.every(isPlainObject)) {
    return null;
  }
  if ((state.blueprint !== undefined && !isBlueprint(state.blueprint)) || (state.artifactMetadata !== undefined && !isArtifactMetadata(state.artifactMetadata))) {
    return null;
  }
  return {
    source: "solutions-architect",
    clientId: state.clientId,
    artifacts: state.artifacts,
    ...(isBlueprint(state.blueprint) ? { blueprint: state.blueprint } : {}),
    ...(isArtifactMetadata(state.artifactMetadata) ? { artifactMetadata: state.artifactMetadata } : {}),
    ...(typeof state.generatedAt === "string" ? { generatedAt: state.generatedAt } : {}),
  };
}

export function solutionDeliveryHandoffStorageKey(clientId: string): string {
  return `${SOLUTION_DELIVERY_HANDOFF_STORAGE_PREFIX}${encodeURIComponent(clientId.trim())}`;
}

export function createSolutionDeliveryHandoff({
  clientId,
  blueprintId,
  blueprintName,
  artifacts,
  generatedAt = new Date().toISOString(),
}: {
  clientId: string;
  blueprintId?: string;
  blueprintName?: string;
  artifacts: HandoffArtifact[];
  generatedAt?: string;
}): SolutionDeliveryHandoff {
  return {
    source: "solutions-architect",
    clientId: clientId.trim(),
    blueprint: { id: blueprintId?.trim() ?? "", name: blueprintName?.trim() || "Standalone builder artifacts" },
    artifacts,
    artifactMetadata: artifacts.map((artifact, index) => ({ id: artifactId(artifact, index), digest: artifactDigest(artifact) })),
    generatedAt,
  };
}

export function writeSolutionDeliveryHandoff(handoff: SolutionDeliveryHandoff): string | null {
  const clientId = handoff.clientId.trim();
  if (!clientId) return null;
  const key = solutionDeliveryHandoffStorageKey(clientId);
  try {
    window.sessionStorage.setItem(key, JSON.stringify(handoff));
    return key;
  } catch {
    return null;
  }
}

export function readStoredSolutionDeliveryHandoff(key: string | null): SolutionDeliveryHandoff | null {
  if (!key || !key.startsWith(SOLUTION_DELIVERY_HANDOFF_STORAGE_PREFIX)) return null;
  try {
    const serialized = window.sessionStorage.getItem(key);
    const handoff = serialized ? readSolutionDeliveryHandoff(JSON.parse(serialized)) : null;
    return handoff && decodeURIComponent(key.slice(SOLUTION_DELIVERY_HANDOFF_STORAGE_PREFIX.length)) === handoff.clientId
      ? handoff
      : null;
  } catch {
    return null;
  }
}

export function clearStoredSolutionDeliveryHandoff(clientId: string): void {
  try {
    window.sessionStorage.removeItem(solutionDeliveryHandoffStorageKey(clientId));
  } catch {
    // Storage may be disabled; the caller still clears its in-memory state.
  }
}

function isBlueprint(value: unknown): value is { id: string; name: string } {
  return isPlainObject(value) && typeof value.id === "string" && typeof value.name === "string";
}

function isArtifactMetadata(value: unknown): value is SolutionDeliveryHandoffArtifact[] {
  return Array.isArray(value) && value.every((item) => (
    isPlainObject(item)
    && typeof item.id === "string"
    && (item.digest === null || typeof item.digest === "string")
  ));
}

function artifactId(artifact: HandoffArtifact, index: number): string {
  for (const field of ["artifact_id", "id", "workflow_id", "app_name", "format"]) {
    if (typeof artifact[field] === "string" && artifact[field].trim()) return artifact[field].trim();
  }
  return `artifact-${index + 1}`;
}

function artifactDigest(artifact: HandoffArtifact): string | null {
  for (const field of ["artifact_digest", "package_digest", "delivery_bundle_digest", "digest"]) {
    if (typeof artifact[field] === "string" && artifact[field].trim()) return artifact[field].trim();
  }
  return null;
}
