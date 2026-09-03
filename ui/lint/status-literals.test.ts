// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { readdirSync, readFileSync } from "node:fs";
// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { dirname, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import allowlist from "./status-literal-allowlist.json";

type AllowlistEntry = { file: string; match: string; count: number; reason: string };

const entries = allowlist.entries as AllowlistEntry[];
const screensRoot = resolve(dirname(import.meta.url.replace("file://", "")), "../src/screens");

describe("status literal guard", () => {
  it("documents every retained status or nullish literal in screen sources", () => {
    const violations = collectViolations();
    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("rejects a deliberately unlisted status literal", () => {
    expect(violationsForSource("src/screens/Example.tsx", '<StatusChip status="deliberate_unlisted_status" />')).toEqual([
      'src/screens/Example.tsx: unlisted StatusChip status="deliberate_unlisted_status" (count 1)',
    ]);
  });
});

function collectViolations(): string[] {
  return screenFiles().flatMap((file) => {
    const relativeFile = relative(resolve(dirname(import.meta.url.replace("file://", "")), ".."), file);
    return violationsForSource(relativeFile, readFileSync(file, "utf8"));
  });
}

function screenFiles(): string[] {
  return readdirSync(screensRoot)
    .filter((file: string) => file.endsWith(".tsx") && !file.endsWith(".test.tsx"))
    .map((file: string) => join(screensRoot, file));
}

export function violationsForSource(file: string, source: string): string[] {
  const matches = [
    ...source.matchAll(/StatusChip\s+status="[^"]+"/g),
    ...source.matchAll(/\?\? "[^"]+"/g),
  ].map((match) => match[0]);
  const counts = new Map<string, number>();
  for (const match of matches) counts.set(match, (counts.get(match) ?? 0) + 1);
  const violations: string[] = [];
  for (const [match, count] of counts) {
    const entry = entries.find((candidate) => candidate.file === file && candidate.match === match);
    if (!entry) {
      violations.push(`${file}: unlisted ${match} (count ${count})`);
    } else if (entry.count !== count) {
      violations.push(`${file}: ${match} expected ${entry.count}, found ${count}`);
    }
  }
  return violations;
}
