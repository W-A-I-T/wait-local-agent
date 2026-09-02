import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { useConfiguredState } from "./useConfiguredState";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);

describe("useConfiguredState", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("is configured only when all required steps are done", async () => {
    mockResponses({ health: { write_actions_enabled: false } });

    const { result } = renderHook(() => useConfiguredState({ role: "admin" }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isConfigured).toBe(true);
    expect(result.current.steps.filter((step) => step.required).every((step) => step.status === "done")).toBe(true);
  });

  it("keeps an unverified mapping incomplete", async () => {
    mockResponses({
      mappings: [{ verified: 0 }],
      health: { write_actions_enabled: false }
    });

    const { result } = renderHook(() => useConfiguredState({ role: "admin" }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isConfigured).toBe(false);
    expect(result.current.steps.find((step) => step.id === "mapping")?.status).toBe("todo");
  });

  it("degrades a rejected fetch to a todo step without throwing", async () => {
    mockResponses({ reject: "/connector-instances", health: { write_actions_enabled: false } });

    const { result } = renderHook(() => useConfiguredState({ role: "admin" }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isConfigured).toBe(false);
    expect(result.current.steps.find((step) => step.id === "connector")?.status).toBe("todo");
  });

  it("reports write health as an informational step", async () => {
    mockResponses({ health: { write_actions_enabled: true } });

    const { result } = renderHook(() => useConfiguredState({ role: "admin" }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    const writes = result.current.steps.find((step) => step.id === "writes");
    expect(writes).toMatchObject({ status: "info", required: false, label: "Live writes enabled" });
  });

  it("resolves loading when the /health response body is null", async () => {
    const options = { health: null };
    mockResponses(options);

    const { result } = renderHook(() => useConfiguredState({ role: "admin" }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.steps.find((step) => step.id === "writes")?.status).toBe("info");
  });

  it("fetches data once and re-derives only the admin step when the role changes", async () => {
    mockResponses();

    const { result, rerender } = renderHook(
      ({ role }: { role: string | null }) => useConfiguredState({ role }),
      { initialProps: { role: "viewer" as string | null } }
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.steps.find((step) => step.id === "admin")?.status).toBe("todo");
    expect(mockedApiFetch).toHaveBeenCalledTimes(2);
    expect(mockedApiFetch.mock.calls.map(([path]) => path)).toEqual([
      "/clients",
      "/health"
    ]);

    rerender({ role: "admin" });

    expect(result.current.steps.find((step) => step.id === "admin")?.status).toBe("done");
    await waitFor(() => expect(result.current.isConfigured).toBe(true));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(6));
    expect(mockedApiFetch.mock.calls.map(([path]) => path).slice(-4)).toEqual([
      "/clients",
      "/connector-instances",
      "/client-connector-mappings",
      "/health"
    ]);
  });

  it("does not call admin-only connector bootstrap endpoints for a technician", async () => {
    mockResponses();

    const { result } = renderHook(() => useConfiguredState({ role: "technician" }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockedApiFetch.mock.calls.map(([path]) => path)).toEqual(["/clients", "/health"]);
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/connector-instances");
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/client-connector-mappings");
  });
});

function mockResponses(options: {
  mappings?: unknown[];
  health?: unknown;
  reject?: string;
} = {}): void {
  mockedApiFetch.mockImplementation((path: string) => {
    if (path === options.reject) {
      return Promise.reject(new Error("endpoint unavailable")) as ReturnType<typeof apiFetch>;
    }
    const responses: Record<string, unknown> = {
      "/clients": [{ client_id: "client-a" }],
      "/connector-instances": [{ connector_instance_id: "connector-a" }],
      "/client-connector-mappings": options.mappings ?? [{ verified: 1 }],
      "/health": options.health === undefined ? { write_actions_enabled: false } : options.health
    };
    return Promise.resolve(responses[path]) as ReturnType<typeof apiFetch>;
  });
}
