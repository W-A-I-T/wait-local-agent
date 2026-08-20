import { beforeEach, describe, expect, it } from "vitest";
import { apiUrl } from "./config";

describe("apiUrl", () => {
  beforeEach(() => {
    delete window.__WAIT_API_BASE__;
  });

  it("honors a desktop API base injected after module evaluation", () => {
    window.__WAIT_API_BASE__ = "http://127.0.0.1:49152/";

    expect(apiUrl("/health")).toBe("http://127.0.0.1:49152/health");
  });
});
