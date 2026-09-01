import { describe, expect, it } from "vitest";
import { catalogPaths, connectorResources, VERIFIED_CONNECTOR_READ_ROUTES } from "./connectorResources";

describe("connector resource catalog", () => {
  it("contains only routes in the verified backend read allowlist", () => {
    expect(catalogPaths().length).toBeGreaterThan(0);
    for (const path of catalogPaths()) {
      expect(VERIFIED_CONNECTOR_READ_ROUTES).toContain(path);
    }
  });

  it("covers the requested connector families and ScalePad QBR resources", () => {
    expect(Object.keys(connectorResources)).toEqual(expect.arrayContaining([
      "servicenow", "itglue", "confluence", "notion", "sharepoint", "scalepad", "syncro",
      "halopsa", "hudu", "connectwise", "autotask", "m365"
    ]));
    expect(connectorResources.scalepad.map((resource) => resource.id)).toEqual(expect.arrayContaining([
      "risk-summaries", "compliance-health", "goals", "assessments"
    ]));
  });
});
