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
  it("requires every declared application route to have visible workspace navigation", () => {
    const routes = routePaths(routesSource);
    const navigation = navigationPaths(
      sidebarSource,
      automationsShellSource,
      activityShellSource
    );

    expect(routes.filter((path) => !navigation.has(path))).toEqual([]);
  });
});
