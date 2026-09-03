import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  apiTokenStorageKey,
  buildApiHeaders,
  clearInMemoryApiToken,
  loadApiToken,
  loadStoredSelectedClientId,
  persistApiToken,
  persistSelectedClientId,
  setSessionApiToken,
  selectedClientStorageKey
} from "./headers";

describe("selected client API scope header", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    clearInMemoryApiToken();
  });

  it("persists a non-secret selected client and sends it as a scope hint", () => {
    persistSelectedClientId(" alpha ");

    expect(loadStoredSelectedClientId()).toBe("alpha");
    expect(window.localStorage.getItem(selectedClientStorageKey)).toBe("alpha");
    expect(buildApiHeaders()).toMatchObject({ "X-WAIT-Client-ID": "alpha" });
    expect(buildApiHeaders()).toMatchObject({ "X-WAIT-CSRF": "1" });
  });

  it("removes the header when no client is selected", () => {
    persistSelectedClientId("alpha");
    persistSelectedClientId("  ");

    expect(loadStoredSelectedClientId()).toBe("");
    expect(buildApiHeaders()).not.toHaveProperty("X-WAIT-Client-ID");
  });

  it("uses a session token before memory and legacy stored credentials", () => {
    persistApiToken("stored-token");
    setSessionApiToken("bootstrap-token");

    expect(buildApiHeaders()).toMatchObject({ Authorization: "Bearer bootstrap-token" });
    expect(window.sessionStorage.getItem(apiTokenStorageKey)).toBe("bootstrap-token");
    expect(window.localStorage.getItem(apiTokenStorageKey)).toBe("stored-token");
  });

  it("loads a session token after the module is re-imported", async () => {
    window.sessionStorage.setItem(apiTokenStorageKey, "bootstrap-token");
    vi.resetModules();

    const reloadedHeaders = await import("./headers");

    expect(reloadedHeaders.loadApiToken()).toBe("bootstrap-token");
  });

  it("falls back to memory when session storage cannot be written", () => {
    const setItem = vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });

    setSessionApiToken("bootstrap-token");

    expect(buildApiHeaders()).toMatchObject({ Authorization: "Bearer bootstrap-token" });
    expect(window.localStorage.getItem(apiTokenStorageKey)).toBeNull();
    setItem.mockRestore();
  });

  it("clears the session token and memory holder together", () => {
    setSessionApiToken("bootstrap-token");
    clearInMemoryApiToken();

    expect(window.sessionStorage.getItem(apiTokenStorageKey)).toBeNull();
    expect(loadApiToken()).toBe("");
  });
});
