export const apiTokenStorageKey = "wait-local-agent-api-token";

export function buildApiHeaders(includeJsonContentType = false): HeadersInit {
  const headers: Record<string, string> = {};
  const token = loadStoredApiToken().trim();
  if (includeJsonContentType) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

export function loadStoredApiToken(): string {
  try {
    return window.localStorage.getItem(apiTokenStorageKey) ?? "";
  } catch {
    return "";
  }
}

export function persistApiToken(token: string): void {
  try {
    if (token.trim()) {
      window.localStorage.setItem(apiTokenStorageKey, token.trim());
      return;
    }
    window.localStorage.removeItem(apiTokenStorageKey);
  } catch {
    return;
  }
}
