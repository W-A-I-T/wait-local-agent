import { describe, expect, it } from "vitest";
import { apiProxyRoutes } from "../src/lib/apiProxyRoutes";

describe("Vite API proxy", () => {
  it("matches the complete API route-family contract", () => {
    expect([...apiProxyRoutes]).toEqual([
      "/health",
      "/auth",
      "/tickets",
      "/agents",
      "/agent-runs",
      "/tools",
      "/smart-actions",
      "/automation",
      "/technician",
      "/end-user",
      "/approval-requests",
      "/audit-events",
      "/audit",
      "/event-history",
      "/knowledge",
      "/workflows",
      "/workflow-templates",
      "/workflow-runs",
      "/consultant",
      "/reports",
      "/hardening",
      "/backups",
      "/backup",
      "/collectors",
      "/analytics",
      "/agent-backfills",
      "/executions",
      "/connectors",
      "/ingestion",
      "/connector-instances",
      "/client-connector-mappings",
      "/clients",
      "/scheduled-jobs",
      "/update-status",
      "/update-check",
      "/founder",
      "/packs",
      "/settings",
      "/secrets",
      "/msp",
      "/mcp"
    ]);
  });
});
