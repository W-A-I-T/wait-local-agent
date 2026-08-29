import { beforeEach, describe, expect, it } from "vitest";
import {
  buildApiHeaders,
  loadStoredSelectedClientId,
  persistSelectedClientId,
  selectedClientStorageKey
} from "./headers";

describe("selected client API scope header", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("persists a non-secret selected client and sends it as a scope hint", () => {
    persistSelectedClientId(" alpha ");

    expect(loadStoredSelectedClientId()).toBe("alpha");
    expect(window.localStorage.getItem(selectedClientStorageKey)).toBe("alpha");
    expect(buildApiHeaders()).toMatchObject({ "X-WAIT-Client-ID": "alpha" });
  });

  it("removes the header when no client is selected", () => {
    persistSelectedClientId("alpha");
    persistSelectedClientId("  ");

    expect(loadStoredSelectedClientId()).toBe("");
    expect(buildApiHeaders()).not.toHaveProperty("X-WAIT-Client-ID");
  });
});
