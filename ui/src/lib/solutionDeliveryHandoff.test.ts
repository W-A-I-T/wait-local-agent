import { describe, expect, it } from "vitest";
import {
  collectHandoffArtifacts,
  readSolutionDeliveryHandoff,
  type SolutionDeliveryHandoff,
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
    { source: "solutions-architect", clientId: "acme", artifacts: {} },
    { source: "solutions-architect", clientId: "acme", artifacts: [] },
    { source: "solutions-architect", clientId: "acme", artifacts: [null] },
  ])("ignores malformed state %#", (state) => {
    expect(readSolutionDeliveryHandoff(state)).toBeNull();
  });
});
