// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { readFileSync } from "node:fs";
// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { dirname, resolve } from "node:path";
// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { apiCalls, normalizePath, requestMethod, sourceTextFor } from "./api-contract-utils";

type OpenApiSnapshot = { paths: Record<string, Record<string, unknown>> };

const fixture = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "fixtures/openapi.json"), "utf8")
) as OpenApiSnapshot;
const calls = apiCalls().filter(({ functionName }) => functionName !== "apiUrl");

// The operation segment is deliberately selected at runtime by the UI. The
// backend publishes one route for each allowed operation, so this call is
// checked by the proxy-family test and the exercised operation tests.
const unmatchedAllowlist = new Map([
  ["/auth/principals/{param}/identities", "the UI method is selected by link or unlink action"],
  ["/agent-backfills/{param}/{param}", "the UI action is selected from the backend backfill controls"],
  ["/agent-runs/{param}/{param}", "the UI action is selected from the backend run controls"],
  ["/discovery/clients/{param}/{param}", "the UI operation is selected from the backend candidate actions"],
  ["/msp/playbook-entries/{param}/{param}", "the UI action is selected from the playbook controls"],
  ["/msp/playbook-subscriptions/{param}/{param}", "the UI action is selected from the subscription controls"],
  ["/packs/agent-platform/iterations/{param}/{param}", "the UI action is selected from the iteration controls"],
  ["/reports/{param}", "the UI report type selects one of the backend report-generation routes"],
  ["/scheduled-jobs/{param}/{param}", "the UI action is selected from the scheduled-job controls"],
  ["/connectors/{param}/write-health", "the configured PSA connector selects the existing write-health route"],
]);

describe("frontend API contract", () => {
  it("extracts a substantial set of static API calls", () => {
    expect(calls.length).toBeGreaterThan(150);
  });

  it("matches every static API call and method to the OpenAPI snapshot", () => {
    const unmatched: string[] = [];
    for (const call of calls) {
      const path = normalizePath(call.path);
      const method = requestMethod(call, sourceTextFor(call));
      const matched = Object.entries(fixture.paths).some(([route, methods]) => {
        if (!Object.keys(methods).some((candidate) => candidate.toLowerCase() === method)) return false;
        const routeParts = normalizePath(route).split("/");
        const callParts = path.split("/");
        return routeParts.length === callParts.length && routeParts.every(
          (part, index) => part === "{param}" || part === callParts[index]
        );
      });
      if (matched) continue;
      if (unmatchedAllowlist.has(path)) continue;
      unmatched.push(`${call.source} ${method.toUpperCase()} ${path}`);
    }
    expect(unmatched, unmatched.join("\n")).toEqual([]);
  });
});
