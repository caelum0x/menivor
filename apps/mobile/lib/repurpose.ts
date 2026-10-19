/**
 * Typed client + presentation helpers for the CONTENT ENGINE — the long-form
 * → shorts pipeline (Opus Clip parity). Two backend engines feed one mobile
 * surface:
 *
 *   1. Repurpose engine (`/repurpose`)  — submit a long recording/URL, then
 *      rank its transcript into AI-scored highlight clips and promote the best
 *      ones into ready-to-submit reel drafts.
 *   2. Clipping engine (`/clipping/jobs`) — a fire-and-forget worker that
 *      auto-produces several vertical, caption-burned shorts from one source.
 *   3. URL ingest (`/ingest/url`) — turn a product/article URL into a hook-first
 *      reel draft (no job created; the draft is submitted to `POST /jobs`).
 *
 * The wire transport (auth via `x-api-key`, JSON envelope unwrapping, typed
 * errors) is the shared api client; this module only adds the typed request
 * functions and side-effect-free domain helpers the screens layer on top.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

// ---------------------------------------------------------------------------
// Repurpose engine
// ---------------------------------------------------------------------------

/** How a repurpose job sources its long video. */
export type RepurposeSourceKind = "upload" | "url";

/** Lifecycle status of a repurpose job (server-defined string). */
export type RepurposeStatus =
  | "created"
  | "transcribing"
  | "ranking"
  | "ranked"
  | "ready"
  | "failed"
  | string;

/** A repurpose job as returned by `job_view` on the backend. */
export interface RepurposeJob {
  readonly id: string;
  readonly source_kind: RepurposeSourceKind | string;
  readonly source_ref: string;
  readonly language: string;
  readonly status: RepurposeStatus;
  readonly title: string;
  readonly duration_s: number;
  readonly clip_count: number;
  readonly error: string;
  readonly created_at: string | null;
}

/** An AI-ranked highlight candidate (`clip_view`). */
export interface RepurposeClip {
  readonly id: string;
  readonly repurpose_job_id: string;
  readonly start_s: number;
  readonly end_s: number;
  readonly length_s: number;
  readonly title: string;
  readonly hook: string;
  readonly transcript: string;
  readonly virality_score: number;
  readonly reason: string;
  readonly status: "suggested" | "promoted" | string;
  readonly reel_job_id: string | null;
}

/** Body for `POST /repurpose`. */
export interface CreateRepurposeBody {
  readonly source_kind: RepurposeSourceKind;
  readonly source_ref: string;
  readonly language?: string;
  readonly title?: string;
}

/** One pre-scored (or unscored) transcript window fed to the ranker. */
export interface TranscriptSegment {
  readonly start_s: number;
  readonly end_s: number;
  readonly text?: string;
  readonly score?: number | null;
  readonly title?: string;
  readonly hook?: string;
  readonly reason?: string;
}

/** Tuning for `POST /repurpose/{id}/rank`. Empty `segments` → LLM auto-rank. */
export interface RankBody {
  readonly segments?: readonly TranscriptSegment[];
  readonly max_clips?: number;
  readonly min_len_s?: number;
  readonly max_len_s?: number;
  readonly min_score?: number;
}

/** A submittable reel draft mapped from a promoted clip. */
export interface ReelDraft {
  readonly video_subject: string;
  readonly video_script: string;
  readonly source_kind: string;
  readonly source_ref: string;
  readonly start_s: number;
  readonly end_s: number;
  readonly hook?: string;
  readonly broll_prompts?: readonly string[];
}

/** Result of promoting a clip. */
export interface PromoteResult {
  readonly clip: RepurposeClip;
  readonly reel_draft: ReelDraft;
}

/** POST /repurpose — start a long-video repurpose job. */
export function createRepurposeJob(
  body: CreateRepurposeBody,
  options?: RequestOptions,
): Promise<RepurposeJob> {
  return request<RepurposeJob>("/repurpose", { method: "POST", body, options });
}

/** GET /repurpose — the caller's repurpose jobs. */
export async function listRepurposeJobs(
  options?: RequestOptions,
): Promise<RepurposeJob[]> {
  const data = await request<{ jobs?: RepurposeJob[] } | RepurposeJob[]>(
    "/repurpose",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.jobs ?? [];
}

/** GET /repurpose/{id} — one job's status. */
export function getRepurposeJob(
  id: string,
  options?: RequestOptions,
): Promise<RepurposeJob> {
  return request<RepurposeJob>(`/repurpose/${encodeURIComponent(id)}`, {
    options,
  });
}

/** POST /repurpose/{id}/rank — rank the transcript into highlight clips. */
export async function rankRepurposeJob(
  id: string,
  body: RankBody = {},
  options?: RequestOptions,
): Promise<RepurposeClip[]> {
  const payload: RankBody = { segments: [], ...body };
  const data = await request<{ clips?: RepurposeClip[] } | RepurposeClip[]>(
    `/repurpose/${encodeURIComponent(id)}/rank`,
    { method: "POST", body: payload, options },
  );
  if (Array.isArray(data)) return data;
  return data?.clips ?? [];
}

/** GET /repurpose/{id}/clips — this job's suggested clips. */
export async function listRepurposeClips(
  id: string,
  options?: RequestOptions,
): Promise<RepurposeClip[]> {
  const data = await request<{ clips?: RepurposeClip[] } | RepurposeClip[]>(
    `/repurpose/${encodeURIComponent(id)}/clips`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.clips ?? [];
}

/** POST /repurpose/clips/{id}/promote — promote a clip to a reel draft. */
export function promoteRepurposeClip(
  clipId: string,
  options?: RequestOptions,
): Promise<PromoteResult> {
  return request<PromoteResult>(
    `/repurpose/clips/${encodeURIComponent(clipId)}/promote`,
    { method: "POST", options },
  );
}

// ---------------------------------------------------------------------------
// Clipping engine (auto long → short worker)
// ---------------------------------------------------------------------------

/** Caption preset for the clipping worker (null skips burned captions). */
export type ClipCaptionPreset = "hormozi" | "ass_karaoke";

/** A clipping worker job status envelope (`_job_view`). */
export interface ClipJob {
  readonly id: string;
  readonly state: string;
  readonly progress: number;
  readonly language: string;
  readonly target_count: number;
  readonly clip_count: number;
  readonly stitched_key: string;
  readonly error: string;
  readonly correlation_id: string;
}

/** A single produced short from the clipping worker. */
export interface ProducedClip {
  readonly id: string;
  readonly clip_job_id: string;
  readonly start_s: number;
  readonly end_s: number;
  readonly length_s: number;
  readonly score: number;
  readonly title: string;
  readonly hook: string;
  readonly transcript: string;
  readonly reason: string;
  readonly aspect: string;
  readonly result_key: string;
  readonly status: string;
}

/** Body for `POST /clipping/jobs`. Exactly one source must be supplied. */
export interface CreateClipJobBody {
  readonly source_video_key?: string;
  readonly source_url?: string;
  readonly language?: string;
  readonly target_count?: number;
  readonly min_len_s?: number;
  readonly max_len_s?: number;
  readonly score_floor?: number;
  readonly captions?: ClipCaptionPreset | null;
  readonly transitions?: boolean;
  readonly publish_targets?: readonly string[];
}

/** The lightweight envelope returned when a clipping job is created. */
export interface ClipJobCreated {
  readonly id: string;
  readonly state: string;
  readonly progress: number;
  readonly correlation_id: string;
}

/** POST /clipping/jobs — enqueue an auto-clipping job. */
export function createClipJob(
  body: CreateClipJobBody,
  options?: RequestOptions,
): Promise<ClipJobCreated> {
  return request<ClipJobCreated>("/clipping/jobs", {
    method: "POST",
    body,
    options,
  });
}

/** GET /clipping/jobs — the caller's clipping jobs. */
export async function listClipJobs(
  options?: RequestOptions,
): Promise<ClipJob[]> {
  const data = await request<{ jobs?: ClipJob[] } | ClipJob[]>(
    "/clipping/jobs",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.jobs ?? [];
}

/** GET /clipping/jobs/{id} — one clipping job's status. */
export function getClipJob(
  id: string,
  options?: RequestOptions,
): Promise<ClipJob> {
  return request<ClipJob>(`/clipping/jobs/${encodeURIComponent(id)}`, {
    options,
  });
}

/** GET /clipping/jobs/{id}/clips — this job's produced clips. */
export async function listProducedClips(
  id: string,
  options?: RequestOptions,
): Promise<ProducedClip[]> {
  const data = await request<{ clips?: ProducedClip[] } | ProducedClip[]>(
    `/clipping/jobs/${encodeURIComponent(id)}/clips`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.clips ?? [];
}

/** POST /clipping/clips/{id}/promote — promote a produced clip to a draft. */
export function promoteProducedClip(
  clipId: string,
  options?: RequestOptions,
): Promise<PromoteResult> {
  return request<PromoteResult>(
    `/clipping/clips/${encodeURIComponent(clipId)}/promote`,
    { method: "POST", options },
  );
}

// ---------------------------------------------------------------------------
// URL ingest
// ---------------------------------------------------------------------------

/** Result of turning a URL into a reel draft (`POST /ingest/url`). */
export interface IngestResult {
  readonly url: string;
  readonly content: {
    readonly title?: string;
    readonly description?: string;
    readonly features?: readonly string[];
    readonly [key: string]: unknown;
  };
  readonly reel_draft: ReelDraft;
}

/** POST /ingest/url — extract a hook-first reel draft from a web page. */
export function ingestUrl(
  url: string,
  options?: RequestOptions,
): Promise<IngestResult> {
  return request<IngestResult>("/ingest/url", {
    method: "POST",
    body: { url },
    options,
  });
}

// ---------------------------------------------------------------------------
// Pure presentation helpers (side-effect free)
// ---------------------------------------------------------------------------

/** Terminal repurpose statuses — no more work will happen automatically. */
const TERMINAL_REPURPOSE: readonly string[] = ["ready", "ranked", "failed"];

export function isRepurposeTerminal(status: string): boolean {
  return TERMINAL_REPURPOSE.includes(status);
}

/** Whether a repurpose job is in a failed state. */
export function isRepurposeFailed(status: string): boolean {
  return status === "failed" || status === "error";
}

/** Whether a repurpose job's transcript is ready to be ranked. */
export function canRankJob(job: RepurposeJob): boolean {
  return !isRepurposeFailed(job.status);
}

/** Terminal clipping worker states. */
const TERMINAL_CLIP_STATES: readonly string[] = [
  "COMPLETED",
  "complete",
  "completed",
  "FAILED",
  "failed",
  "CANCELLED",
  "cancelled",
  "canceled",
];

export function isClipJobTerminal(state: string): boolean {
  return TERMINAL_CLIP_STATES.includes(state);
}

export function isClipJobFailed(state: string): boolean {
  const s = state.toLowerCase();
  return s === "failed" || s === "cancelled" || s === "canceled";
}

/** A signal color for a job status/state string. */
export function statusColor(status: string): string {
  const s = status.toLowerCase();
  if (s === "ready" || s === "ranked" || s.includes("complet")) return "#5DB585";
  if (s === "failed" || s === "error" || s.includes("cancel")) return "#D0605B";
  if (s === "created" || s === "queued" || s === "pending") return "#A49CE0";
  return "#E6C76A";
}

/** Color-code a 0..100 virality score. */
export function scoreColor(score: number): string {
  if (score >= 80) return "#5DB585";
  if (score >= 60) return "#E6C76A";
  if (score >= 40) return "#e6923b";
  return "#9b978d";
}

/** Human "mm:ss" for a second offset. */
export function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/** "0:12 – 0:41 · 29s" span label for a clip. */
export function formatSpan(startS: number, endS: number): string {
  const length = Math.max(0, Math.round(endS - startS));
  return `${formatClock(startS)} – ${formatClock(endS)} · ${length}s`;
}

/** Friendly local date for an ISO timestamp (blank when absent/invalid). */
export function formatJobDate(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  try {
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

/** A readable title for a repurpose job, falling back to its source/id. */
export function repurposeJobTitle(job: RepurposeJob): string {
  const title = (job.title ?? "").trim();
  if (title) return title;
  const ref = (job.source_ref ?? "").trim();
  if (ref) return ref.length > 42 ? `${ref.slice(0, 42)}…` : ref;
  return job.id;
}

/** A readable label for a produced-clip title/hook, falling back to its id. */
export function clipTitle(title: string, hook: string, id: string): string {
  const t = (title || "").trim();
  if (t) return t;
  const h = (hook || "").trim();
  if (h) return h;
  return id;
}

/** Whether a promoted-or-suggested clip can still be promoted. */
export function clipIsPromotable(status: string): boolean {
  return status !== "promoted";
}

/** Detect a URL source ref so the submit form can validate correctly. */
export function looksLikeUrl(value: string): boolean {
  const v = value.trim().toLowerCase();
  return v.startsWith("http://") || v.startsWith("https://");
}
