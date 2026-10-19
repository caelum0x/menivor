/**
 * Typed client for the render-job engine — Expo.
 *
 * Submit a render spec to a backend (e.g. RunPod), then poll the job by
 * advancing it until it reaches a terminal state.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export type RenderState =
  | "PENDING"
  | "QUEUED"
  | "IN_QUEUE"
  | "RUNNING"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface RenderJob {
  id: string;
  backend: string;
  state: RenderState;
  progress: number;
  output_refs: string[];
  cost_micros: number;
  error?: string;
  /** Browser/device-usable URLs: bare R2 keys presigned, public URLs passed through. */
  output_urls?: string[];
  /** Refs the API could not turn into a playable URL (LAN-only, garbage). */
  unusable_output_refs?: number;
  created_at?: string | null;
  updated_at?: string | null;
  held_cost_micros?: number;
  actual_cost_micros?: number;
  /** Where the render came from: "render" (direct), "film" (a film shot/export)… */
  source?: string;
  label?: string;
}

export interface CreateRenderJobBody {
  backend: string;
  spec: { prompt: string };
  max_cost_micros: number;
}

const TERMINAL_STATES: readonly RenderState[] = ["COMPLETED", "FAILED", "CANCELLED"];

export function isTerminalState(state: RenderState): boolean {
  return TERMINAL_STATES.includes(state);
}

/**
 * Only a non-terminal render job can be canceled. Cancelling releases the wallet
 * hold in full (success-only billing), so the guard here is purely lifecycle.
 */
export function isCancelableState(state: RenderState): boolean {
  return !isTerminalState(state);
}

/** A human display label for a raw render state. */
export function renderStateLabel(state: RenderState): string {
  switch (state) {
    case "PENDING":
      return "Pending";
    case "QUEUED":
    case "IN_QUEUE":
      return "Queued";
    case "RUNNING":
    case "IN_PROGRESS":
      return "Running";
    case "COMPLETED":
      return "Completed";
    case "FAILED":
      return "Failed";
    case "CANCELLED":
      return "Canceled";
    default:
      return state;
  }
}

/** A signal color for a render lifecycle state, drawn from the shared palette. */
export function renderStateColor(state: RenderState): string {
  switch (state) {
    case "COMPLETED":
      return "#5DB585";
    case "FAILED":
      return "#D0605B";
    case "CANCELLED":
      return "#9b978d";
    case "RUNNING":
    case "QUEUED":
    case "PENDING":
    default:
      return "#E6C76A";
  }
}

export function createRenderJob(
  body: CreateRenderJobBody,
  options?: RequestOptions,
): Promise<RenderJob> {
  return request<RenderJob>("/render/jobs", { method: "POST", body, options });
}

export function getRenderJob(id: string, options?: RequestOptions): Promise<RenderJob> {
  return request<RenderJob>(`/render/jobs/${encodeURIComponent(id)}`, { options });
}

export function advanceRenderJob(id: string, options?: RequestOptions): Promise<RenderJob> {
  return request<RenderJob>(`/render/jobs/${encodeURIComponent(id)}/advance`, {
    method: "POST",
    options,
  });
}

/**
 * Cancel a render job and release its wallet hold (full refund — success-only
 * billing). Safe to call on a non-terminal job; returns the terminal snapshot.
 */
export function cancelRenderJob(id: string, options?: RequestOptions): Promise<RenderJob> {
  return request<RenderJob>(`/render/jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    options,
  });
}

/**
 * The caller's render history via `GET /render/jobs` (owner-scoped, newest
 * first). The API may return the list directly or wrapped as `{ jobs }`.
 */
export async function listRenderJobs(
  query?: { limit?: number; state?: RenderState | string },
  options?: RequestOptions,
): Promise<RenderJob[]> {
  const params: string[] = [];
  if (query?.limit) params.push(`limit=${encodeURIComponent(String(query.limit))}`);
  if (query?.state) params.push(`state=${encodeURIComponent(String(query.state))}`);
  const qs = params.length ? `?${params.join("&")}` : "";
  const data = await request<RenderJob[] | { jobs?: RenderJob[]; items?: RenderJob[] }>(
    `/render/jobs${qs}`,
    { options },
  );
  const rows = Array.isArray(data) ? data : data?.jobs ?? data?.items ?? [];
  return rows.map((row) => ({ ...row, output_refs: row.output_refs ?? [] }));
}

/**
 * Playable/downloadable URLs for a render job: the API's presigned
 * `output_urls` when present, otherwise any ref that is already an absolute
 * https URL. Bare storage keys are never returned (the device cannot sign them).
 */
export function renderPlayableUrls(job: RenderJob): string[] {
  if (Array.isArray(job.output_urls) && job.output_urls.length > 0) {
    return job.output_urls;
  }
  return (job.output_refs ?? []).filter((ref) => /^https:\/\//i.test(ref));
}

const IMAGE_URL = /\.(png|jpe?g|webp|gif)(\?|$)/i;

/** Whether a render output URL is a still image (vs. a video). */
export function isImageOutput(url: string): boolean {
  return IMAGE_URL.test(url);
}
