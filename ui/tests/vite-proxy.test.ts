import { describe, expect, it } from "vitest";
import { apiProxyRoutes } from "../src/lib/apiProxyRoutes";
import { apiCalls, firstPathSegment } from "./api-contract-utils";

describe("Vite API proxy", () => {
  it("includes every static API path family used by the source", () => {
    const routes: Set<string> = new Set(apiProxyRoutes);
    const missing = apiCalls()
      .map(({ path }) => firstPathSegment(path))
      .filter((path): path is string => path !== null && !routes.has(path));
    expect(missing).toEqual([]);
    expect(apiCalls().length).toBeGreaterThan(150);
  });
});
