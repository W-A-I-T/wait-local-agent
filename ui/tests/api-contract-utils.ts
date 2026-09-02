// The UI package intentionally does not carry a Node type dependency just for
// these filesystem-only tests; Vitest supplies the Node built-ins at runtime.
// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { readdirSync, readFileSync } from "node:fs";
// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { dirname, join, resolve } from "node:path";
// @ts-expect-error Node types are not a runtime dependency of the UI package.
import { fileURLToPath } from "node:url";

export type ApiCall = {
  functionName: "apiFetch" | "apiFetchBlob" | "apiUrl";
  path: string;
  source: string;
};

const TESTS_ROOT = dirname(fileURLToPath(import.meta.url));
const SOURCE_ROOT = resolve(TESTS_ROOT, "../src");
const CALL_PATTERN = /\b(apiFetchBlob|apiFetch|apiUrl)\b/g;

export function sourceFiles(): string[] {
  return walk(SOURCE_ROOT).filter((file) => {
    if (!/\.(ts|tsx)$/.test(file)) return false;
    if (/\.(test|spec)\.(ts|tsx)$/.test(file)) return false;
    return !file.split("/").includes("__tests__");
  });
}

export function apiCalls(): ApiCall[] {
  return sourceFiles().flatMap((file) => extractCalls(readFileSync(file, "utf8"), file));
}

function walk(directory: string): string[] {
  const entries = readdirSync(directory, { withFileTypes: true }) as Array<{ name: string; isDirectory(): boolean }>;
  return entries.flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

function extractCalls(source: string, file: string): ApiCall[] {
  const calls: ApiCall[] = [];
  for (const match of source.matchAll(CALL_PATTERN)) {
    const functionName = match[1] as ApiCall["functionName"];
    let cursor = (match.index ?? 0) + match[0].length;
    cursor = skipWhitespace(source, cursor);
    if (source[cursor] === "<") cursor = skipBalanced(source, cursor, "<", ">");
    cursor = skipWhitespace(source, cursor);
    if (source[cursor] !== "(") continue;
    cursor = skipWhitespace(source, cursor + 1);
    const literal = readLiteral(source, cursor);
    if (!literal) continue;
    calls.push({ functionName, path: literal.value, source: `${file}:${match.index}` });
  }
  return calls;
}

function skipWhitespace(source: string, cursor: number): number {
  while (/\s/.test(source[cursor] ?? "")) cursor += 1;
  return cursor;
}

function skipBalanced(source: string, cursor: number, opening: string, closing: string): number {
  let depth = 0;
  for (; cursor < source.length; cursor += 1) {
    if (source[cursor] === opening) depth += 1;
    if (source[cursor] === closing && --depth === 0) return cursor + 1;
  }
  return source.length;
}

function readLiteral(source: string, cursor: number): { value: string; end: number } | null {
  const quote = source[cursor];
  if (quote !== "'" && quote !== '"' && quote !== "`") return null;
  let value = "";
  for (let index = cursor + 1; index < source.length; index += 1) {
    const character = source[index];
    if (character === "\\") {
      value += source[index + 1] ?? "";
      index += 1;
    } else if (quote === "`" && character === "$" && source[index + 1] === "{") {
      const expressionEnd = findInterpolationEnd(source, index + 2);
      if (expressionEnd === -1) return null;
      value += "{param}";
      index = expressionEnd;
    } else if (character === quote) {
      return { value, end: index + 1 };
    } else {
      value += character;
    }
  }
  return null;
}

function findInterpolationEnd(source: string, cursor: number): number {
  let depth = 1;
  for (let index = cursor; index < source.length; index += 1) {
    const character = source[index];
    if (character === "\\") {
      index += 1;
    } else if (character === "'" || character === '"' || character === "`") {
      index = skipString(source, index, character);
    } else if (character === "{") {
      depth += 1;
    } else if (character === "}" && --depth === 0) {
      return index;
    }
  }
  return -1;
}

function skipString(source: string, cursor: number, quote: string): number {
  for (let index = cursor + 1; index < source.length; index += 1) {
    const character = source[index];
    if (character === "\\") {
      index += 1;
    } else if (quote === "`" && character === "$" && source[index + 1] === "{") {
      const expressionEnd = findInterpolationEnd(source, index + 2);
      if (expressionEnd === -1) return source.length;
      index = expressionEnd;
    } else if (character === quote) {
      return index;
    }
  }
  return source.length;
}

function findCallEnd(source: string, openParen: number): number {
  let depth = 0;
  let quote = "";
  for (let index = openParen; index < source.length; index += 1) {
    const character = source[index];
    if (quote) {
      if (character === "\\") index += 1;
      else if (character === quote) quote = "";
      continue;
    }
    if (character === "'" || character === '"' || character === "`") {
      quote = character;
    } else if (character === "(") {
      depth += 1;
    } else if (character === ")" && --depth === 0) {
      return index + 1;
    }
  }
  return source.length;
}

export function normalizePath(path: string): string {
  const pathOnly = path
    .replace(/\$\{[^}]*\}/g, "{param}")
    .split(/[?#]/, 1)[0]
    .split("/")
    .map((segment) => {
      if (!segment.startsWith("{param}")) return segment.split("{param}", 1)[0];
      return "{param}";
    })
    .join("/");
  return pathOnly.replace(/\{[^/}]+\}/g, "{param}");
}

export function requestMethod(call: ApiCall, sourceText: string): string {
  const start = sourceText.indexOf(call.functionName, Number(call.source.split(":").pop()));
  const end = findCallEnd(sourceText, sourceText.indexOf("(", start));
  const method = sourceText.slice(start, end).match(/\bmethod\s*:\s*["'](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)["']/i);
  return (method?.[1] ?? "GET").toLowerCase();
}

export function firstPathSegment(path: string): string | null {
  return normalizePath(path).match(/^\/[^/]+/)?.[0] ?? null;
}

export function sourceTextFor(call: ApiCall): string {
  return readFileSync(call.source.slice(0, call.source.lastIndexOf(":")), "utf8");
}
