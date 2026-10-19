/**
 * Renderer API client for the ReelForge backend v1 API.
 *
 * Every AUTHENTICATED call is proxied through the preload bridge
 * (`window.reelforge.request`) so the API base URL and the API token live ONLY in
 * the main process (token encrypted at rest via `safeStorage`) and never enter the
 * renderer bundle. Main attaches the `x-api-key` header, prefixes the configured
 * base, unwraps the `{ status, data, message }` envelope, and throws a plain
 * `Error` on any non-2xx — mirroring `web/lib/api.ts::request<T>()` minus the auth
 * plumbing. The one direct network call (the presigned R2 PUT) lives in
 * `./upload` and needs no secret.
 *
 * No secrets are ever hardcoded here: the API base + token are read from secure
 * config in main and surfaced (non-secret parts only) via {@link getConfig}.
 */

import type {
  Job,
  JobCreateRequest,
  JobCreateResult,
  PresignRequest,
  PresignResult,
} from "./types";
import type {
  ApiRequestInput,
  ConfigPatch,
  HttpMethod,
  PublicConfig,
} from "../../electron/ipc";

// ---------------------------------------------------------------------------
// Core typed request helper (thin, validated wrapper over the preload bridge)
// ---------------------------------------------------------------------------

/** Options for a single {@link request} call. */
export interface RequestOptions {
  method?: HttpMethod;
  /** JSON-serialisable request body (for POST/PUT/PATCH). */
  body?: unknown;
}

/**
 * Perform one authenticated API call against the configured base, returning the
 * unwrapped `data` payload typed as `T`. The token + base are attached in main;
 * this is a typed façade over `window.reelforge.request` so callers get a single,
 * consistent entry point (parallel to the web client's `request<T>()`).
 *
 * `path` must begin with `/` (re-validated in main); anything else throws before a
 * request is made.
 */
export function request<T>(path: string, options?: RequestOptions): Promise<T> {
  if (typeof path !== "string" || !path.startsWith("/")) {
    return Promise.reject(
      new Error('Invalid API request: "path" must begin with "/".'),
    );
  }
  const input: ApiRequestInput = {
    method: options?.method ?? "GET",
    path,
    body: options?.body,
  };
  return window.reelforge.request<T>(input);
}

// ---------------------------------------------------------------------------
// Secure config (non-secret view) — the API base + whether a token is set live
// in main; the renderer reads them through the preload bridge, never the token.
// ---------------------------------------------------------------------------

/** Read the current non-secret config `{ apiBase, tokenSet }` from main. */
export function getConfig(): Promise<PublicConfig> {
  return window.reelforge.getConfig();
}

/** Persist a validated config patch (`apiBase`/`token`); returns the new config. */
export function saveConfig(patch: ConfigPatch): Promise<PublicConfig> {
  return window.reelforge.saveConfig(patch);
}

/** Convenience: the configured API base URL (no trailing slash). */
export async function getApiBase(): Promise<string> {
  const { apiBase } = await getConfig();
  return apiBase;
}

// ---------------------------------------------------------------------------
// §5 endpoints
// ---------------------------------------------------------------------------

/** POST /uploads/presign — obtain a presigned R2 PUT URL + final object key. */
export function presign(body: PresignRequest): Promise<PresignResult> {
  return request<PresignResult>("/uploads/presign", { method: "POST", body });
}

/** POST /jobs — create + enqueue a ReelForge job from a screen recording. */
export function createJob(body: JobCreateRequest): Promise<JobCreateResult> {
  return request<JobCreateResult>("/jobs", { method: "POST", body });
}

/** GET /jobs/{id} — the current status/result of a single job. */
export function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`);
}

/**
 * GET /jobs — the caller's job history. The backend may return the list directly
 * as `data` or wrapped as `{ jobs: [...] }`; both shapes are normalized to a
 * `Job[]` here so callers always get an array.
 */
export async function listJobs(): Promise<Job[]> {
  const data = await request<Job[] | { jobs?: Job[] }>("/jobs");
  if (Array.isArray(data)) return data;
  return data?.jobs ?? [];
}

// ---------------------------------------------------------------------------
// Re-exports — keep a single import surface (`../lib/api`) for the renderer while
// the implementations live in focused modules.
// ---------------------------------------------------------------------------

export { presignAndUpload } from "./upload";
export type { UploadResult, UploadProgress } from "./upload";
export {
  pollJob,
  useJob,
  POLL_INTERVAL_MS,
  DEFAULT_MAX_POLL_ATTEMPTS,
} from "./useJob";
export type { PollOptions, UseJobResult } from "./useJob";
