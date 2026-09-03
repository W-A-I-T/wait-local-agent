import { describe, expect, it } from "vitest";
import {
  collectHandoffArtifacts,
  clearStoredSolutionDeliveryHandoff,
  createSolutionDeliveryHandoff,
  readSolutionDeliveryHandoff,
  readStoredSolutionDeliveryHandoff,
  solutionDeliveryHandoffStorageKey,
  type SolutionDeliveryHandoff,
  writeSolutionDeliveryHandoff,
} from "./solutionDeliveryHandoff";

describe("solution delivery handoff", () => {
  const apps = { format: "wait-local-agent.power-apps-artifact" };
  const flow = { format: "wait-local-agent.power-automate-flow-plan" };

  it("collects artifacts in the stable Power Apps then flow order", () => {
    expect(collectHandoffArtifacts(apps, flow)).toEqual([apps, flow]);
    expect(collectHandoffArtifacts(apps, null)).toEqual([apps]);
    expect(collectHandoffArtifacts(undefined, flow)).toEqual([flow]);
    expect(collectHandoffArtifacts(null, undefined)).toEqual([]);
    expect(collectHandoffArtifacts([apps], flow)).toEqual([flow]);
    expect(collectHandoffArtifacts("apps", 42)).toEqual([]);
  });

  it("reads a well-formed handoff and narrows its contents", () => {
    const handoff: SolutionDeliveryHandoff = {
      source: "solutions-architect",
      clientId: "acme",
      artifacts: [apps, flow],
    };

    expect(readSolutionDeliveryHandoff(handoff)).toEqual(handoff);
  });

  it.each([
    null,
    undefined,
    "x",
    [],
    { source: "other", clientId: "acme", artifacts: [apps] },
    { source: "solutions-architect", clientId: 42, artifacts: [apps] },
    { source: "solutions-architect", clientId: " ", artifacts: [apps] },
    { source: "solutions-architect", clientId: "acme", artifacts: {} },
    { source: "solutions-architect", clientId: "acme", artifacts: [] },
    { source: "solutions-architect", clientId: "acme", artifacts: [null] },
  ])("ignores malformed state %#", (state) => {
    expect(readSolutionDeliveryHandoff(state)).toBeNull();
  });

  it("persists and clears a blueprint-named handoff for the selected client", () => {
    const handoff = createSolutionDeliveryHandoff({
      clientId: "acme",
      blueprintId: "bp-acme",
      blueprintName: "Employee onboarding",
      artifacts: [{ workflow_id: "onboarding", artifact_digest: "sha256:flow" }],
      generatedAt: "2026-09-03T18:00:00.000Z",
    });
    const key = writeSolutionDeliveryHandoff(handoff);

    expect(key).toBe(solutionDeliveryHandoffStorageKey("acme"));
    expect(readStoredSolutionDeliveryHandoff(key)).toEqual(handoff);
    expect(readStoredSolutionDeliveryHandoff(solutionDeliveryHandoffStorageKey("other"))).toBeNull();
    clearStoredSolutionDeliveryHandoff("acme");
    expect(readStoredSolutionDeliveryHandoff(key)).toBeNull();
  });
});
