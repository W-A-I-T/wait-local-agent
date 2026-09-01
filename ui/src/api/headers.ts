export const apiTokenStorageKey = "wait-local-agent-api-token";
export const selectedClientStorageKey = "wait-local-agent-selected-client";

export function buildApiHeaders(includeJsonContentType = false): HeadersInit {
  const headers: Record<string, string> = { "X-WAIT-CSRF": "1" };
  const token = loadStoredApiToken().trim();
  const selectedClientId = loadStoredSelectedClientId().trim();
  if (includeJsonContentType) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (selectedClientId) {
    headers["X-WAIT-Client-ID"] = selectedClientId;
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

export function loadStoredSelectedClientId(): string {
  try {
    return window.localStorage.getItem(selectedClientStorageKey) ?? "";
  } catch {
    return "";
  }
}

export function persistSelectedClientId(clientId: string): void {
  try {
    if (clientId.trim()) {
      window.localStorage.setItem(selectedClientStorageKey, clientId.trim());
      return;
    }
    window.localStorage.removeItem(selectedClientStorageKey);
  } catch {
    return;
  }
}
