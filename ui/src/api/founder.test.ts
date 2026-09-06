import { describe, expect, it } from "vitest";
import { projectFounderUploadPreview } from "./founder";

describe("Founder upload preview", () => {
  it("shows permitted environment key names while excluding values and credential-shaped strings", () => {
    const result = projectFounderUploadPreview({
      env_key_names: ["EXAMPLE_API_KEY", "DB_PASSWORD", "PUBLIC_NAME", "API_KEY=fixture-value", "Bearer fixture", ["sk", "test", "fixture123"].join("_"), "xoxb-fixture123", 17],
    }, "local-artifact");
    expect(result?.env_key_names).toEqual(["EXAMPLE_API_KEY", "DB_PASSWORD", "PUBLIC_NAME"]);
  });
});
