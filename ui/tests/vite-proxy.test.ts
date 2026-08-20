import { describe, expect, it } from "vitest";
import { apiProxyRoutes } from "../src/lib/apiProxyRoutes";

describe("Vite API proxy", () => {
  it("proxies every UI API family to the local appliance", () => {
    const configuredRoutes = new Set<string>(apiProxyRoutes);
    expect([
      "/agents",
      "/agent-runs",
      "/tools",
      "/smart-actions",
      "/automation",
      "/technician",
      "/end-user",
      "/reports",
      "/hardening",
      "/backup",
      "/collectors",
      "/update-check",
      "/msp",
      "/mcp"
    ].every((route) => configuredRoutes.has(route))).toBe(true);
  });
});
