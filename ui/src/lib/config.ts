declare global {
  interface Window {
    __WAIT_API_BASE__?: string;
  }
}

export const API_BASE = import.meta.env.VITE_API_BASE ?? window.__WAIT_API_BASE__ ?? "";

export function apiUrl(path: string): string {
  if (!API_BASE) {
    return path;
  }
  return `${API_BASE.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}
