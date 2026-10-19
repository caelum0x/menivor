/**
 * Minimal authenticated transport for the standalone editor route.
 *
 * The preserved editor module does not run inside the Next.js/Clerk runtime, so
 * it cannot reuse `@/lib/api`. This is a small, dependency-free client that
 * speaks the SAME wire protocol as the product client
 * (`apps/web/src/shared/api/client.ts`): an `x-api-key` credential, the
 * `{ status, data, message }` envelope, and the same job/timeline-export routes.
 *
 * Credential resolution mirrors the product device-session flow: an explicit
 * per-call token wins, else the device api-key persisted by the main app in
 * localStorage under `menivor.device.api_key`. Base URL comes from the Vite env
 * (`VITE_API_BASE`) and defaults to the local API.
 */

import type { EditorJob, MusicCatalogEntry, TimelineExportBody } from "./editor-model";

const DEFAULT_API_BASE = "http://localhost:8080/api/v1";
const DEVICE_API_KEY_STORAGE = "menivor.device.api_key";

function readEnvBase(): string {
  // Vite exposes string env on import.meta.env; guard for non-Vite (test) runs.
  try {
    const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
    const value = env?.VITE_API_BASE;
    if (value && value.trim()) return value.trim();
  } catch {
    // import.meta not available (e.g. CommonJS test) — fall through to default.
  }
  return DEFAULT_API_BASE;
}

export const API_BASE: string = readEnvBase().replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly correlationId?: string;

  constructor(message: string, status: number, correlationId?: string) {
    super(
      correlationId && !message.includes(correlationId)
        ? `${message} (correlation ${correlationId})`
        : message,
    );
    this.name = "ApiError";
    this.status = status;
    this.correlationId = correlationId || undefined;
  }
}

export interface RequestOptions {
  token?: string;
  signal?: AbortSignal;
  idempotencyKey?: string;
}

/** The device api-key persisted by the main web app, when running in a browser. */
function storedDeviceApiKey(): string {
  if (typeof window === "undefined" || !window.localStorage) return "";
  try {
    return window.localStorage.getItem(DEVICE_API_KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

function resolveCredential(options: RequestOptions | undefined): string {
  if (options?.token) return options.token;
  return storedDeviceApiKey();
}

interface Envelope<T> {
  status?: number;
  data?: T;
  message?: string | null;
}

async function request<T>(
  path: string,
  init: { method?: string; body?: unknown; options?: RequestOptions } = {},
): Promise<T> {
  const { method = "GET", body, options } = init;
  const hasBody = body !== undefined;
  const credential = resolveCredential(options);

  const headers: Record<string, string> = {};
  if (credential) headers["x-api-key"] = credential;
  if (hasBody) headers["Content-Type"] = "application/json";
  if (options?.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: hasBody ? JSON.stringify(body) : undefined,
      signal: options?.signal,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      `Network error contacting the API: ${error instanceof Error ? error.message : String(error)}`,
      0,
    );
  }

  const raw = await response.text();
  let envelope: Envelope<T> | null = null;
  if (raw) {
    try {
      envelope = JSON.parse(raw) as Envelope<T>;
    } catch {
      envelope = null;
    }
  }

  if (!response.ok) {
    const correlationId = response.headers.get("X-Correlation-ID") || undefined;
    throw new ApiError(
      envelope?.message || `Request failed with status ${response.status} ${response.statusText}`.trim(),
      response.status,
      correlationId,
    );
  }
  if (envelope === null) {
    throw new ApiError("Malformed response: expected a JSON envelope from the API.", response.status);
  }
  return (envelope.data ?? (envelope as unknown as T)) as T;
}

export const POLL_INTERVAL_MS = 3000;

/** GET /jobs/{id} — the source reel snapshot (poll until terminal). */
export function getJob(id: string, options?: RequestOptions): Promise<EditorJob> {
  return request<EditorJob>(`/jobs/${encodeURIComponent(id)}`, { options });
}

/** GET /catalog/music — the curated background-music track library. */
export function listMusic(options?: RequestOptions): Promise<MusicCatalogEntry[]> {
  return request<MusicCatalogEntry[]>("/catalog/music", { options });
}

/** POST /jobs/{id}/timeline-exports — enqueue the multi-clip EDL export. */
export function createTimelineExport(
  id: string,
  body: TimelineExportBody,
  options?: RequestOptions,
): Promise<EditorJob> {
  return request<EditorJob>(`/jobs/${encodeURIComponent(id)}/timeline-exports`, {
    method: "POST",
    body,
    options,
  });
}

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return fallback;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `editor-${crypto.randomUUID()}`;
  }
  return `editor-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
