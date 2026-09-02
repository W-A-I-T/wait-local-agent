import { describe, expect, it, vi } from "vitest";
import {
  ApiRequestError,
  CLIENT_SCOPE_ERROR_MESSAGE,
  apiErrorMessage,
  apiFetch,
  apiFetchBlob,
  isCapabilityRequiredDetail,
  isClientScopeErrorDetail,
} from "../src/api/client";

describe("apiFetch", () => {
  it("requests JSON and rejects an HTML SPA response for an API request", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(() => Promise.resolve(new Response("<html>SPA</html>", {
      status: 200,
      headers: { "Content-Type": "text/html" }
    })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/clients")).rejects.toMatchObject({
      message: "The appliance returned an unexpected response. Try again.",
      technicalDetail: "/clients received HTML for an API request; check caching or proxy configuration",
      status: 200
    } satisfies Partial<ApiRequestError>);
    const jsonRequest = fetchMock.mock.calls[0]?.[1] ?? {};
    expect(new Headers(jsonRequest.headers).get("Accept")).toBe("application/json");

    vi.unstubAllGlobals();
  });

  it("keeps blob requests on a non-JSON Accept header", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(() => Promise.resolve(new Response(new Uint8Array([37, 80, 68, 70]), {
      headers: { "Content-Type": "application/pdf" }
    })));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetchBlob("/reports/report-1/export?export_format=pdf");

    const blobRequest = fetchMock.mock.calls[0]?.[1] ?? {};
    expect(new Headers(blobRequest.headers).get("Accept")).toBe("*/*");
    vi.unstubAllGlobals();
  });

  it("uses plain language for transport failures while retaining technical detail", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "token rejected" }), { status: 403 }))));

    await expect(apiFetch("/auth/role")).rejects.toMatchObject({
      message: "You do not have permission to do that. Check your access and try again.",
      technicalDetail: "/auth/role failed with HTTP 403: token rejected"
    } satisfies Partial<ApiRequestError>);

    vi.unstubAllGlobals();
  });

  it.each([
    "authenticated principal has no tenant",
    "requested tenant is outside authenticated scope",
    "operation requires a single client scope",
    "client scope is required",
    "chat sessions require a client scope",
    "knowledge ingestion requires a client scope",
    "employee-onboarding demo requires a tenant scope",
    "reports require a client scope",
    "Notion reads require a tenant scope",
    "execution lists require a single client or all-client scope",
    "capability operation requires one explicit client",
    "client_id is required for a scheduled report",
    "client_id is required to generate a client report",
    "client_id is required for a playbook subscription",
  ])("explains client-scope failures for %s", async (detail) => {
    const status = detail === "client_id is required for a scheduled report" ? 400 : 403;
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail }), { status }))));

    await expect(apiFetch("/scope-sensitive-action")).rejects.toMatchObject({
      message: CLIENT_SCOPE_ERROR_MESSAGE,
      technicalDetail: `/scope-sensitive-action failed with HTTP ${status}: ${detail}`,
      detail,
    } satisfies Partial<ApiRequestError>);

    vi.unstubAllGlobals();
  });

  it("keeps unrelated forbidden responses generic", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "role is insufficient" }), { status: 403 }))));

    await expect(apiFetch("/admin-only-action")).rejects.toMatchObject({
      message: "You do not have permission to do that. Check your access and try again.",
      technicalDetail: "/admin-only-action failed with HTTP 403: role is insufficient",
    } satisfies Partial<ApiRequestError>);

    vi.unstubAllGlobals();
  });

  it("keeps the classifier narrow for unrelated details", () => {
    expect(isClientScopeErrorDetail("insufficient role")).toBe(false);
    expect(apiErrorMessage(403, "insufficient role")).toBe("You do not have permission to do that. Check your access and try again.");
  });

  it("preserves structured capability details for capability-gated screens", async () => {
    const detail = {
      code: "capability_required",
      capability: "microsoft_admin",
      reason: "no_grant",
      remediation: "grant_capability",
    };
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail }), { status: 403 }))));

    const error = await apiFetch("/capability-gated-action").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiRequestError);
    expect(error).toMatchObject({
      message: "You do not have permission to do that. Check your access and try again.",
      detail,
    });
    expect(isCapabilityRequiredDetail((error as ApiRequestError).detail)).toBe(true);

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
