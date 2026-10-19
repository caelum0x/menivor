/** Shared authenticated transport for every ReelForge web feature. */

import { getStoredDeviceApiKey, refreshDeviceSession } from "../device/session";
import { API_BASE } from "./base";
import { getSessionToken } from "./session-token";

export { API_BASE } from "./base";

const APP_API_KEY = process.env.NEXT_PUBLIC_APP_API_KEY || "";

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

export interface RequestOptions {
  token?: string;
  signal?: AbortSignal;
  /** Stable create-request key retained across ambiguous transport retries. */
  idempotencyKey?: string;
}

export interface ApiRequestInit {
  method?: string;
  body?: unknown;
  options?: RequestOptions;
  /** Public routes opt out of both the Clerk token and fallback app key. */
  anonymous?: boolean;
}

interface ApiEnvelope<T> {
  status?: number;
  data?: T;
  message?: string | null;
}

function buildHeaders(
  credential: string,
  options: RequestOptions | undefined,
  hasBody: boolean,
): Record<string, string> {
  const headers: Record<string, string> = {};
  if (credential) headers["x-api-key"] = credential;
  if (hasBody) headers["Content-Type"] = "application/json";
  if (options?.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }
  return headers;
}

/**
 * Resolve the credential for a request. Order: an explicit per-call token
 * (Clerk JWT) > the signed-in session token (registered by ApiSessionBridge)
 * > a device-session key this browser ALREADY holds (legacy guest
 * sessions from before sign-up became mandatory; new ones are never minted on
 * the web) > the static public app key. Server-side there is no device store,
 * so the chain degrades to token/app-key exactly as before.
 */
async function resolveCredential(
  options: RequestOptions | undefined,
  anonymous: boolean,
): Promise<{ credential: string; isDeviceKey: boolean }> {
  if (anonymous) return { credential: "", isDeviceKey: false };
  if (options?.token) return { credential: options.token, isDeviceKey: false };
  if (typeof window !== "undefined") {
    const session = await getSessionToken();
    if (session) return { credential: session, isDeviceKey: false };
    const stored = getStoredDeviceApiKey();
    if (stored) return { credential: stored, isDeviceKey: true };
  }
  return { credential: APP_API_KEY, isDeviceKey: false };
}

/**
 * The credential a hand-rolled `fetch` (streams, uploads) should send as
 * `x-api-key`: the same chain `apiRequest` uses, so signed-in, legacy device
 * and app-key callers all authenticate the same way.
 */
export async function resolveApiCredential(options?: RequestOptions): Promise<string> {
  return (await resolveCredential(options, false)).credential;
}

const READ_RETRY_DELAYS_MS = [700, 2000];
// Edge/tunnel gateway errors only: an app 503 carries a real message and shows at once.
const RETRYABLE_STATUS = new Set([502, 504, 520, 521, 522, 523, 524, 530]);

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Run a GET, retrying network errors and edge gateway errors twice with backoff. */
export async function withReadRetry(
  run: () => Promise<Response>,
  delays: readonly number[] = READ_RETRY_DELAYS_MS,
): Promise<Response> {
  for (let attempt = 0; ; attempt += 1) {
    const last = attempt >= delays.length;
    try {
      const response = await run();
      if (last || !RETRYABLE_STATUS.has(response.status)) return response;
    } catch (error) {
      if (last || (error instanceof DOMException && error.name === "AbortError")) throw error;
    }
    await sleep(delays[attempt] ?? 0);
  }
}

export async function apiRequest<T>(
  path: string,
  init: ApiRequestInit = {},
): Promise<T> {
  const { method = "GET", body, options, anonymous = false } = init;
  const hasBody = body !== undefined;
  let { credential, isDeviceKey } = await resolveCredential(options, anonymous);

  const once = (cred: string): Promise<Response> =>
    fetch(`${API_BASE}${path}`, {
      method,
      headers: buildHeaders(cred, options, hasBody),
      body: hasBody ? JSON.stringify(body) : undefined,
      signal: options?.signal,
      cache: "no-store",
    });
  // Reads ride out a short API restart (the edge answers 502/52x/530 without
  // CORS headers, which the browser reports as a network error).
  const send = method.toUpperCase() === "GET" ? (cred: string) => withReadRetry(() => once(cred)) : once;

  let response: Response;
  try {
    response = await send(credential);
    // A 401 on a stored device key means the key no longer matches the
    // server (e.g. its device secret rotated). Re-exchange the install id
    // once — same account, fresh key — and retry transparently.
    if (response.status === 401 && isDeviceKey) {
      try {
        const session = await refreshDeviceSession();
        credential = session.api_key;
        response = await send(credential);
      } catch {
        // Keep the original 401 response for uniform error handling below.
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
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
    // Auth failures carry internal detail ("<request id>: missing x-api-key
    // header"); users only need to know their session needs a refresh.
    const message =
      response.status === 401
        ? "Your session expired. Refresh the page or sign in again."
        : envelope?.message ||
          `Request failed with status ${response.status} ${response.statusText}`.trim();
    throw new ApiError(
      message,
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
