import { describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiFetch } from "../src/api/client";

describe("apiFetch", () => {
  it("uses plain language for transport failures while retaining technical detail", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "token rejected" }), { status: 403 }))));

    await expect(apiFetch("/auth/role")).rejects.toMatchObject({
      message: "You do not have permission to do that. Check your access and try again.",
      technicalDetail: "/auth/role failed with HTTP 403: token rejected"
    } satisfies Partial<ApiRequestError>);

    vi.unstubAllGlobals();
  });
});
