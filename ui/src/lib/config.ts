declare global {
  interface Window {
    __WAIT_API_BASE__?: string;
  }
}

export function getApiBase(): string {
  // Tauri injects the sidecar URL after the bundle is evaluated. Read the
  // runtime override for every request so late injection is honored.
  return import.meta.env.VITE_API_BASE ?? (typeof window !== "undefined" ? window.__WAIT_API_BASE__ : undefined) ?? "";
}

// Kept for callers that need the build-time value; request construction must
// use getApiBase() because the desktop override is runtime state.
export const API_BASE = getApiBase();

export function apiUrl(path: string): string {
  const apiBase = getApiBase();
  if (!apiBase) {
    return path;
  }
  return `${apiBase.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}
