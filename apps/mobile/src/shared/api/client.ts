/** Shared authenticated transport for ReelForge Expo features. */

import { isDemoMode } from "@/src/shared/release/build-flags";
import { demoResponse } from "@/src/shared/release/demo-api";

/** Production API; the fallback for any on-device build without an override. */
const PRODUCTION_API_BASE = "https://api.menivor.com/api/v1";
/** Local backend for Metro dev sessions (simulator / emulator). */
const LOCAL_API_BASE = "http://localhost:8080/api/v1";

declare const __DEV__: boolean | undefined;

const DEFAULT_API_BASE =
  typeof __DEV__ !== "undefined" && __DEV__ ? LOCAL_API_BASE : PRODUCTION_API_BASE;

export const API_BASE: string = (
  process.env.EXPO_PUBLIC_API_BASE || DEFAULT_API_BASE
).replace(/\/+$/, "");

const APP_API_KEY = process.env.EXPO_PUBLIC_APP_API_KEY || "";

export const POLL_INTERVAL_MS = 3000;

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: unknown;
  readonly correlationId?: string;

  constructor(
    message: string,
    status: number,
    detail?: unknown,
    correlationId?: string,
  ) {
    super(
      correlationId && !message.includes(correlationId)
        ? `${message} (correlation ${correlationId})`
        : message,
    );
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.correlationId = correlationId || undefined;
  }
}

export function makeAbortError(message = "Aborted"): Error {
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export interface RequestOptions {
  token?: string;
  signal?: AbortSignal;
  /** Stable create-request key retained across ambiguous transport retries. */
  idempotencyKey?: string;
}

interface ApiEnvelope<T> {
  status?: number;
  data?: T;
  message?: string | null;
}

function buildHeaders(options: RequestOptions | undefined, hasBody: boolean): Record<string, string> {
  const headers: Record<string, string> = {};
  const credential = options?.token || APP_API_KEY;
  if (credential) headers["x-api-key"] = credential;
  if (hasBody) headers["Content-Type"] = "application/json";
  if (options?.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }
  return headers;
}

export async function apiRequest<T>(
  path: string,
  init: { method?: string; body?: unknown; options?: RequestOptions } = {},
): Promise<T> {
  const { method = "GET", body, options } = init;
  const hasBody = body !== undefined;
  if (isDemoMode()) {
    // Dev-only seeded workspace (screenshots). Never true in a store build.
    try {
      return demoResponse(method, path) as T;
    } catch (error) {
      throw new ApiError(
        error instanceof Error ? error.message : "Not part of the demo workspace.",
        503,
      );
    }
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: buildHeaders(options, hasBody),
      body: hasBody ? JSON.stringify(body) : undefined,
      signal: options?.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(
      `Network error contacting the API: ${
        error instanceof Error ? error.message : String(error)
      }`,
      0,
      error,
    );
  }

  const raw = await response.text();
  let envelope: ApiEnvelope<T> | null = null;
  if (raw) {
    try {
      envelope = JSON.parse(raw) as ApiEnvelope<T>;
    } catch {
      envelope = null;
    }
  }
  if (!response.ok) {
    const correlationId = response.headers.get("X-Correlation-ID") || undefined;
    throw new ApiError(
      envelope?.message || `Request failed with status ${response.status}`,
      response.status,
      envelope ?? raw,
      correlationId,
    );
  }
  if (envelope === null) {
    throw new ApiError(
      "Malformed response: expected a JSON envelope from the API.",
      response.status,
      raw,
    );
  }
  return (envelope.data ?? (envelope as unknown as T)) as T;
}
