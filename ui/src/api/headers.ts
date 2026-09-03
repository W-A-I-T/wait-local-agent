export const apiTokenStorageKey = "wait-local-agent-api-token";
export const selectedClientStorageKey = "wait-local-agent-selected-client";

let inMemoryApiToken = "";

export function buildApiHeaders(includeJsonContentType = false): HeadersInit {
  const headers: Record<string, string> = { "Accept": "application/json", "X-WAIT-CSRF": "1" };
  const token = loadApiToken().trim();
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

export function setSessionApiToken(token: string): void {
  const normalizedToken = token.trim();
  inMemoryApiToken = normalizedToken;
  try {
    if (normalizedToken) {
      window.sessionStorage.setItem(apiTokenStorageKey, normalizedToken);
    } else {
      window.sessionStorage.removeItem(apiTokenStorageKey);
    }
  } catch {
    // Keep the token in memory when browser storage is unavailable.
  }
}

export function clearInMemoryApiToken(): void {
  inMemoryApiToken = "";
  try {
    window.sessionStorage.removeItem(apiTokenStorageKey);
  } catch {
    return;
  }
}

export function loadApiToken(): string {
  return loadSessionApiToken() || inMemoryApiToken || loadStoredApiToken();
}

function loadSessionApiToken(): string {
  try {
    return window.sessionStorage.getItem(apiTokenStorageKey)?.trim() ?? "";
  } catch {
    return "";
  }
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
