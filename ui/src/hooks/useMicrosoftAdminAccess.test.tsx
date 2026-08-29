import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDashboard } from "../app/DashboardContext";
import { useMicrosoftAdminAccess, type CapabilityGrantView } from "./useMicrosoftAdminAccess";

vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedDashboard = vi.mocked(useDashboard);
const refreshDashboard = vi.fn(async () => {});

function dashboard(
  selectedClientId: string,
  grants: CapabilityGrantView[] = [],
  options: { resolved?: boolean; error?: string; roleResolved?: boolean } = {}
) {
  mockedDashboard.mockReturnValue({
    selectedClientId,
    roleResolved: options.roleResolved ?? true,
    capabilityGrants: grants,
    capabilityResolved: options.resolved ?? true,
    capabilityError: options.error ?? "",
    refresh: refreshDashboard
  } as never);
}

describe("useMicrosoftAdminAccess", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("allows the selected client only when its grant exists", () => {
    dashboard("alpha", [{ capability_key: "microsoft_admin", client_id: "alpha" }]);

    const { result, rerender } = renderHook(() => useMicrosoftAdminAccess());
    expect(result.current.resolved).toBe(true);
    expect(result.current.allowed).toBe(true);

    dashboard("beta", [{ capability_key: "microsoft_admin", client_id: "alpha" }]);
    rerender();
    expect(result.current.allowed).toBe(false);
  });

  it("accepts an explicit global grant", () => {
    dashboard("beta", [{ capability_key: "microsoft_admin", client_id: null }]);

    const { result } = renderHook(() => useMicrosoftAdminAccess());

    expect(result.current.resolved).toBe(true);
    expect(result.current.allowed).toBe(true);
  });

  it("fails closed when effective access cannot be read", () => {
    dashboard("alpha", [], { resolved: true, error: "denied" });

    const { result } = renderHook(() => useMicrosoftAdminAccess());

    expect(result.current.allowed).toBe(false);
    expect(result.current.grants).toEqual([]);
    expect(result.current.error).toBe("denied");
  });

  it("stays unresolved until both role and capability state are resolved", () => {
    dashboard("alpha", [{ capability_key: "microsoft_admin", client_id: "alpha" }], {
      resolved: false
    });

    const { result, rerender } = renderHook(() => useMicrosoftAdminAccess());
    expect(result.current.resolved).toBe(false);
    expect(result.current.allowed).toBe(false);

    dashboard("alpha", [{ capability_key: "microsoft_admin", client_id: "alpha" }], {
      resolved: true,
      roleResolved: false
    });
    rerender();
    expect(result.current.resolved).toBe(false);
    expect(result.current.allowed).toBe(false);
  });

  it("delegates explicit refresh to the authenticated dashboard session", async () => {
    dashboard("alpha");
    const { result, rerender } = renderHook(() => useMicrosoftAdminAccess());
    expect(result.current.allowed).toBe(false);

    await act(async () => {
      await result.current.refresh();
    });
    expect(refreshDashboard).toHaveBeenCalledTimes(1);

    dashboard("alpha", [{ capability_key: "microsoft_admin", client_id: "alpha" }]);
    rerender();
    expect(result.current.allowed).toBe(true);
  });
});
