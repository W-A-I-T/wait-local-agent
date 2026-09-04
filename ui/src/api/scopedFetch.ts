import { apiFetch } from "./client";

export function apiFetchForClient<T>(clientId: string, path: string, init?: RequestInit): Promise<T> {
  const normalizedClientId = clientId.trim();
  if (!normalizedClientId) {
    return init === undefined ? apiFetch<T>(path) : apiFetch<T>(path, init);
  }
  const headers = new Headers(init?.headers);
  headers.set("X-WAIT-Client-ID", normalizedClientId);
  return apiFetch<T>(path, { ...init, headers });
}
