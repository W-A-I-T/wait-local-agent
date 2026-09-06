import { describe, expect, it } from "vitest";
import { projectFounderResults, projectFounderUploadPreview } from "./founder";

describe("Founder upload preview", () => {
  it("shows permitted environment key names while excluding values and credential-shaped strings", () => {
    const result = projectFounderUploadPreview({
      env_key_names: ["EXAMPLE_API_KEY", "DB_PASSWORD", "PUBLIC_NAME", "API_KEY=fixture-value", "Bearer fixture", ["sk", "test", "fixture123"].join("_"), "xoxb-fixture123", 17],
    }, "local-artifact");
    expect(result?.env_key_names).toEqual(["EXAMPLE_API_KEY", "DB_PASSWORD", "PUBLIC_NAME"]);
  });

  it.each([{ available: false }, { status: "unavailable", error: "Fixture provider unavailable" }, {}])("does not turn an empty or unavailable report into success: %j", (latest_report) => {
    expect(projectFounderResults({ latest_report })?.latest_report.available).toBe(false);
  });

  it("preserves an explicitly available report and a legacy report reference", () => {
    expect(projectFounderResults({ latest_report: { available: true } })?.latest_report.available).toBe(true);
    expect(projectFounderResults({ latest_report: { id: "report-1" } })?.latest_report.available).toBe(true);
  });
});
