import { apiUrl } from "../lib/config";
import { buildApiHeaders } from "./headers";

export class ApiRequestError extends Error {
  readonly technicalDetail: string;
  readonly status?: number;
  readonly detail?: unknown;

  constructor(message: string, technicalDetail: string, status?: number, detail?: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.technicalDetail = technicalDetail;
    this.status = status;
    this.detail = detail;
  }
}

export const CLIENT_SCOPE_ERROR_MESSAGE = "This action needs a specific client selected. Choose one from the top bar and try again.";

const CLIENT_SCOPE_ERROR_SUBSTRINGS = [
  "authenticated principal has no tenant",
  "requested tenant is outside authenticated scope",
  "operation requires a single client scope",
  "client scope is required",
  "requires a client scope",
  "require a client scope",
  "requires one explicit client",
  "requires a single client",
  "require a single client",
  "requires a tenant",
  "require a tenant",
  "outside the configured tenant scope",
  "client_id is required for a scheduled report",
  "client_id is required to generate a client report",
  "client_id is required for a playbook subscription",
] as const;

export function isClientScopeErrorDetail(detail: unknown): detail is string {
  return typeof detail === "string" && CLIENT_SCOPE_ERROR_SUBSTRINGS.some((substring) => detail.includes(substring));
}

export function shouldSuppressClientScopeError(
  error: unknown,
  clientScopeIds: string[] | null | undefined,
  isMspAdmin: boolean | undefined
): boolean {
  if (isMspAdmin || !Array.isArray(clientScopeIds) || clientScopeIds.length > 0) {
    return false;
  }
  return error instanceof ApiRequestError
    ? isClientScopeErrorDetail(error.detail) || error.message === CLIENT_SCOPE_ERROR_MESSAGE
    : error instanceof Error && isClientScopeErrorDetail(error.message);
}

export type CapabilityRequiredDetail = {
  code: "capability_required";
  capability?: unknown;
  reason?: unknown;
  remediation?: unknown;
};

export function isCapabilityRequiredDetail(detail: unknown): detail is CapabilityRequiredDetail {
  return Boolean(detail && typeof detail === "object" && (detail as Record<string, unknown>).code === "capability_required");
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(buildApiHeaders(Boolean(init.body)));
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { ...init, headers });
  } catch (error) {
    throw new ApiRequestError(
      "We couldn't connect to the appliance. Check that it is available, then try again.",
      `${path} request could not be completed: ${error instanceof Error ? error.message : String(error)}`
    );
  }

  if (headers.get("Accept")?.toLowerCase().includes("application/json") && response.headers.get("content-type")?.toLowerCase().includes("text/html")) {
    throw new ApiRequestError(
      "The appliance returned an unexpected response. Try again.",
      `${path} received HTML for an API request; check caching or proxy configuration`,
      response.status
    );
  }

  let payload: unknown;
  try {
    payload = await readResponsePayload(response);
  } catch (error) {
    throw new ApiRequestError(
      "The appliance sent an unreadable response. Try again.",
      `${path} response could not be read: ${error instanceof Error ? error.message : String(error)}`
    );
  }

  if (!response.ok) {
    const detail = extractErrorDetail(payload);
    throw new ApiRequestError(apiErrorMessage(response.status, detail), `${path} failed with HTTP ${response.status}${errorSuffix(payload)}`, response.status, detail);
  }

  return payload as T;
}

export async function apiFetchBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  const headers = new Headers(buildApiHeaders(Boolean(init.body)));
  if (!new Headers(init.headers).has("Accept")) {
    headers.set("Accept", "*/*");
  }
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { ...init, headers });
  } catch (error) {
    throw new ApiRequestError(
      "We couldn't connect to the appliance. Check that it is available, then try again.",
      `${path} request could not be completed: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  if (!response.ok) {
    let payload: unknown;
    try {
      payload = await readResponsePayload(response);
    } catch {
      payload = undefined;
    }
    const detail = extractErrorDetail(payload);
    throw new ApiRequestError(apiErrorMessage(response.status, detail), `${path} failed with HTTP ${response.status}${errorSuffix(payload)}`, response.status, detail);
  }
  return response.blob();
}

async function readResponsePayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function errorSuffix(payload: unknown): string {
  const detail = extractErrorDetail(payload);
  if (typeof detail === "string" && detail) {
    return `: ${detail}`;
  }
  return "";
}

function extractErrorDetail(payload: unknown): unknown {
  if (typeof payload === "string") {
    return payload;
  }
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    return record.detail ?? record.message ?? record.error;
  }
  return undefined;
}

export function apiErrorMessage(status: number, detail?: unknown): string {
  if (isClientScopeErrorDetail(detail)) {
    return CLIENT_SCOPE_ERROR_MESSAGE;
  }
  if (detail && typeof detail === "object") {
    const code = (detail as Record<string, unknown>).code;
    if (code === "m365_throttled") {
      return "Microsoft 365 is temporarily busy. Try again shortly.";
    }
    if (code === "m365_auth_required") {
      return "Microsoft 365 access needs to be reconnected. Check the connection and try again.";
    }
    if (code === "m365_insufficient_permission") {
      return "This Microsoft 365 connection does not have the required permission.";
    }
  }
  if (status === 401 || status === 403) {
    return "You do not have permission to do that. Check your access and try again.";
  }
  if (status === 404) {
    return "That information is no longer available. Refresh and try again.";
  }
  if (status === 409) {
    return "That action conflicts with the appliance's current state. Refresh and try again.";
  }
  if (status === 429) {
    return "The appliance is handling too many requests right now. Wait a moment and try again.";
  }
  if (status >= 500) {
    return "The appliance couldn't complete the request. Try again shortly.";
  }
  return "The request could not be completed. Check the details and try again.";
}
