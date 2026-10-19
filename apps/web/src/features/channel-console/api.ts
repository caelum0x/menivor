/**
 * Channel console API — connected OAuth accounts, the scheduled-publish queue,
 * and 1-body/N-hooks retention A/B experiments.
 *
 * All calls flow through the shared authenticated transport (`apiRequest`),
 * which unwraps the MPT `{ data }` envelope and raises `ApiError` on failure.
 * Mutating POSTs accept an `idempotencyKey` (via `RequestOptions`) so an
 * ambiguous transport retry never double-schedules or double-creates.
 *
 * These functions target the REAL backend routes:
 * * `GET  /me/connections`            — connected providers (bare data array)
 * * `POST /jobs/{job_id}/schedule`    — queue a completed job to auto-publish
 * * `GET  /me/scheduled`              — the caller's schedules (bare data array)
 * * `POST /experiments`               — create a 1-body/N-hooks experiment
 * * `GET  /experiments/{key}`         — the experiment + its variants + verdict
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

/** A social account the workspace has connected for direct publishing.
 *
 * TOKEN-FREE: the backend never serialises an access/refresh token — only the
 * provider, the provider-side account id, the connection status and scopes. */
export interface Channel {
  provider: string;
  external_account_id: string;
  connected: boolean;
  /** `connected` | `expired`. */
  status: string;
  scopes: string;
  token_expires_at?: string | null;
  connected_at?: string | null;
  updated_at?: string | null;
}

/** Body for `POST /jobs/{job_id}/schedule` — one or more platforms + a future UTC time. */
export interface ScheduleBody {
  /** Target platforms (e.g. `tiktok`, `instagram`, `youtube_shorts`). */
  platforms: string[];
  /** ISO-8601 UTC timestamp; must be in the future. */
  scheduled_at: string;
  /** YouTube privacy status (defaults to `private` server-side). */
  youtube_privacy_status?: string;
}

/** A single queued publish (the `ScheduledPublish` public envelope). */
export interface ScheduledPost {
  id: string;
  job_id: string;
  platforms: string[];
  scheduled_at: string | null;
  status: string;
  youtube_privacy_status?: string | null;
  attempts?: number | null;
  error?: string;
}

/** Body for `POST /experiments` — one body ref, N (>=2) hook variants. */
export interface CreateExperimentBody {
  experiment_key: string;
  hook_refs: string[];
  body_ref?: string;
}

/** One hook arm of an experiment with its retention metrics. */
export interface ExperimentVariant {
  id: string;
  hook_ref: string;
  views: number;
  completion_rate: number;
  avg_watch_frac: number;
  rewatch_rate: number;
  engagement_rate: number;
}

/** An experiment with its persisted hook variants and (once evaluated) verdict. */
export interface Experiment {
  id: string;
  experiment_key: string;
  status: string;
  body_ref: string;
  winner_variant_id: string | null;
  winner_hook_ref: string | null;
  variants: ExperimentVariant[];
}

/** GET /me/connections — the caller's connected accounts (bare `data` array). */
export function listChannels(options?: RequestOptions): Promise<Channel[]> {
  return apiRequest<Channel[]>("/me/connections", { options });
}

/** POST /jobs/{job_id}/schedule — queue a completed, owned job for a future publish. */
export function schedulePost(
  jobId: string,
  body: ScheduleBody,
  options?: RequestOptions,
): Promise<ScheduledPost> {
  return apiRequest<ScheduledPost>(
    `/jobs/${encodeURIComponent(jobId)}/schedule`,
    { method: "POST", body, options },
  );
}

/** GET /me/scheduled — the caller's scheduled-publish queue (bare `data` array). */
export function listScheduled(
  options?: RequestOptions,
): Promise<ScheduledPost[]> {
  return apiRequest<ScheduledPost[]>("/me/scheduled", { options });
}

/** POST /experiments — create a 1-body/N-hooks retention experiment. */
export function createExperiment(
  body: CreateExperimentBody,
  options?: RequestOptions,
): Promise<Experiment> {
  return apiRequest<Experiment>("/experiments", {
    method: "POST",
    body,
    options,
  });
}

/** GET /experiments/{key} — the experiment, its variants and current verdict. */
export function getExperiment(
  experimentKey: string,
  options?: RequestOptions,
): Promise<Experiment> {
  return apiRequest<Experiment>(
    `/experiments/${encodeURIComponent(experimentKey)}`,
    { options },
  );
}

/** Format an ISO instant for compact display; falls back to the raw string. */
export function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
