import { beforeEach, describe, expect, it } from "vitest";
import {
  apiTokenStorageKey,
  buildApiHeaders,
  clearInMemoryApiToken,
  loadStoredSelectedClientId,
  persistApiToken,
  persistSelectedClientId,
  setInMemoryApiToken,
  selectedClientStorageKey
} from "./headers";

describe("selected client API scope header", () => {
  beforeEach(() => {
    window.localStorage.clear();
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

  it("uses a tab-only token before any stored credential", () => {
    persistApiToken("stored-token");
    setInMemoryApiToken("bootstrap-token");

    expect(buildApiHeaders()).toMatchObject({ Authorization: "Bearer bootstrap-token" });
    expect(window.localStorage.getItem(apiTokenStorageKey)).toBe("stored-token");
  });
});
