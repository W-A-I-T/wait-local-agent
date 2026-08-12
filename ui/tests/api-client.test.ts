import { describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiFetch, apiFetchBlob } from "../src/api/client";

describe("apiFetch", () => {
  it("uses plain language for transport failures while retaining technical detail", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "token rejected" }), { status: 403 }))));

    await expect(apiFetch("/auth/role")).rejects.toMatchObject({
      message: "You do not have permission to do that. Check your access and try again.",
      technicalDetail: "/auth/role failed with HTTP 403: token rejected"
    } satisfies Partial<ApiRequestError>);

    vi.unstubAllGlobals();
  });

  it("explains rate limiting instead of presenting it as an unknown failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "slow down" }), { status: 429 }))));

    await expect(apiFetch("/connectors/halopsa/tickets")).rejects.toMatchObject({
      message: "The appliance is handling too many requests right now. Wait a moment and try again.",
      technicalDetail: "/connectors/halopsa/tickets failed with HTTP 429: slow down",
      status: 429
    } satisfies Partial<ApiRequestError>);

    vi.unstubAllGlobals();
  });

  it("returns binary report exports without parsing them as text", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(new Uint8Array([37, 80, 68, 70])))));

    const blob = await apiFetchBlob("/reports/report-1/export?export_format=pdf");

    expect(blob.size).toBe(4);
    vi.unstubAllGlobals();
  });
});
