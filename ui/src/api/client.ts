import { apiUrl } from "../lib/config";
import { buildApiHeaders } from "./headers";

export class ApiRequestError extends Error {
  readonly technicalDetail: string;
  readonly status?: number;

  constructor(message: string, technicalDetail: string, status?: number) {
    super(message);
    this.name = "ApiRequestError";
    this.technicalDetail = technicalDetail;
    this.status = status;
  }
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
    throw new ApiRequestError(apiErrorMessage(response.status), `${path} failed with HTTP ${response.status}${errorSuffix(payload)}`, response.status);
  }

  return payload as T;
}

export async function apiFetchBlob(path: string, init: RequestInit = {}): Promise<Blob> {
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
  if (!response.ok) {
    let payload: unknown;
    try {
      payload = await readResponsePayload(response);
    } catch {
      payload = undefined;
    }
    throw new ApiRequestError(apiErrorMessage(response.status), `${path} failed with HTTP ${response.status}${errorSuffix(payload)}`, response.status);
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
  if (typeof payload === "string" && payload) {
    return `: ${payload}`;
  }
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const detail = record.detail ?? record.message ?? record.error;
    if (typeof detail === "string" && detail) {
      return `: ${detail}`;
    }
  }
  return "";
}

function apiErrorMessage(status: number): string {
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
