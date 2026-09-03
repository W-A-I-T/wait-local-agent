import { describe, expect, it } from "vitest";

import routesSource from "./routes.tsx?raw";
import sidebarSource from "./app/Sidebar.tsx?raw";
import automationsShellSource from "./app/AutomationsShell.tsx?raw";
import activityShellSource from "./app/ActivityShell.tsx?raw";

function routePaths(source: string): string[] {
  return [...source.matchAll(/<Route\s+path="([^"]+)"/g)]
    .map((match) => `/${match[1]}`)
    .filter((path) => path !== "/login" && path !== "/*");
}

function navigationPaths(...sources: string[]): Set<string> {
  return new Set(sources.flatMap((source) => [...source.matchAll(/to:\s*"([^"]+)"/g)].map((match) => match[1])));
}

describe("route reachability", () => {
  it("keeps the primary operator journey visible and legacy paths declared", () => {
    const routes = routePaths(routesSource);
    const navigation = navigationPaths(
      sidebarSource,
      automationsShellSource,
      activityShellSource
    );

    const primaryJourney = [
      "/", "/clients", "/client-discovery", "/connectors", "/integrations/connector-instances",
      "/workflows", "/approvals", "/activity/runs", "/consultant", "/consultant/solution-delivery",
      "/settings", "/settings/access", "/system/appliance-health", "/system/diagnostics",
      "/system/extensions", "/integrations/mcp"
    ];
    expect(primaryJourney.filter((path) => !navigation.has(path))).toEqual([]);
    expect(["/automation/events", "/automation/schedules", "/scheduled-jobs", "/backfills", "/executions", "/smart-actions/runs", "/end-user"]
      .filter((path) => !routes.includes(path))).toEqual([]);
  });
});
