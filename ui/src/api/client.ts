import { apiUrl } from "../lib/config";
import { buildApiHeaders } from "./headers";

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(buildApiHeaders(Boolean(init.body)));
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  const response = await fetch(apiUrl(path), { ...init, headers });
  const payload = await readResponsePayload(response);

  if (!response.ok) {
    throw new Error(`${path} failed with HTTP ${response.status}${errorSuffix(payload)}`);
  }

  return payload as T;
}

async function readResponsePayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function errorSuffix(payload: unknown): string {
  if (typeof payload === "string" && payload) {
    return `: ${payload}`;
  }
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const detail = record.detail ?? record.message ?? record.error;
    if (typeof detail === "string" && detail) {
      return `: ${detail}`;
    }
  }
  return "";
}
