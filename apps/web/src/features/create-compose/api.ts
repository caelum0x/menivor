/**
 * Create-compose transport: turn a template instantiation into a render job,
 * then poll that job to completion.
 *
 * Flow: `instantiateTemplate` (templates feature) → {@link compileReel} →
 * {@link pollCompileJob}. The instantiation's `reel_draft` is already a
 * `JobCreateRequest`-shaped payload (the backend validates it against that DTO),
 * so the compile step simply POSTs that draft to the canonical `POST /jobs`
 * create endpoint — there is no separate `/reels/compile` route.
 */

import { apiRequest, POLL_INTERVAL_MS, type RequestOptions } from "@/src/shared/api";
import {
  pollUntilTerminal,
  type PollResult,
} from "@/src/features/media-gateway/poll";
import type { InstantiateResult, ReelDraft } from "@/src/features/templates/api";

/**
 * Request body for `POST /jobs` — the instantiation's pipeline-ready reel draft.
 * This is exactly the `JobCreateRequest`-shaped `reel_draft` the backend's
 * template `instantiate` bridge produces (it may also carry backend-only extras
 * like `background_id`/`character` that ride through to `Job.params`).
 */
export type CompileBody = ReelDraft;

/** `POST /jobs` envelope `.data` (single-variant create). */
export interface CompileResult {
  job_id: string;
  state?: number;
  progress?: number;
}

/**
 * `GET /jobs/{id}` envelope `.data`. The product contract is `status` +
 * `asset_url`; the current backend also emits the numeric `state`/`result_url`
 * pair, so both are accepted and normalised by the helpers below rather than
 * assuming one shape.
 */
export interface JobSnapshot {
  job_id: string;
  status?: string;
  asset_url?: string;
  /** Backend numeric lifecycle (`1` complete, `-1` failed). */
  state?: number;
  progress?: number;
  result_url?: string;
  error?: string;
}

/** Optional slot-preview request body for `POST /media/videos`. */
export interface SlotPreviewBody {
  prompt: string;
  duration_s?: number;
  aspect?: string;
}

/** `POST /media/videos` envelope `.data` (best-effort, provider-shaped). */
export interface SlotPreviewResult {
  job_id?: string;
  asset_url?: string;
  url?: string;
}

const TERMINAL_STATUSES = new Set(["completed", "complete", "failed", "error"]);
const FAILED_STATUSES = new Set(["failed", "error"]);

/** True once the job has succeeded or failed (polling stops here). */
export function isJobTerminal(job: JobSnapshot): boolean {
  if (typeof job.state === "number") {
    return job.state === 1 || job.state === -1;
  }
  return TERMINAL_STATUSES.has((job.status ?? "").toLowerCase());
}

/** True when the job reached a terminal *failure* state. */
export function isJobFailed(job: JobSnapshot): boolean {
  if (job.state === -1) return true;
  return FAILED_STATUSES.has((job.status ?? "").toLowerCase());
}

/** The playable/downloadable asset, preferring the product `asset_url` field. */
export function jobAssetUrl(job: JobSnapshot): string | undefined {
  return job.asset_url ?? job.result_url ?? undefined;
}

/** POST the pipeline-ready reel draft to `POST /jobs` and return the new job id. */
export function compileReel(
  body: CompileBody,
  options?: RequestOptions,
): Promise<CompileResult> {
  return apiRequest<CompileResult>("/jobs", {
    method: "POST",
    body,
    options,
  });
}

/** Extract the pipeline-ready reel draft from an instantiation (immutable passthrough). */
export function compileBodyFrom(result: InstantiateResult): CompileBody {
  return result.reel_draft;
}

/** Read a single render job's status. */
export function getJob(
  jobId: string,
  options?: RequestOptions,
): Promise<JobSnapshot> {
  return apiRequest<JobSnapshot>(`/jobs/${encodeURIComponent(jobId)}`, {
    options,
  });
}

export interface PollCompileOptions {
  token?: string;
  signal?: AbortSignal;
  onTick?: (job: JobSnapshot) => void;
  intervalMs?: number;
  maxMs?: number;
}

/**
 * Poll `GET /jobs/{id}` every {@link POLL_INTERVAL_MS} until the job is terminal
 * or the deadline elapses. Returns the last snapshot plus a `timedOut` flag.
 */
export function pollCompileJob(
  jobId: string,
  opts: PollCompileOptions = {},
): Promise<PollResult<JobSnapshot>> {
  return pollUntilTerminal(
    () => getJob(jobId, { token: opts.token, signal: opts.signal }),
    isJobTerminal,
    {
      intervalMs: opts.intervalMs ?? POLL_INTERVAL_MS,
      maxMs: opts.maxMs,
      onTick: opts.onTick,
    },
  );
}

/** Optional per-slot preview clip via the media gateway. */
export function previewSlotVideo(
  body: SlotPreviewBody,
  options?: RequestOptions,
): Promise<SlotPreviewResult> {
  return apiRequest<SlotPreviewResult>("/media/videos", {
    method: "POST",
    body,
    options,
  });
}
