/**
 * Typed client for the Clipfarm (unattended channel-runner) domain — Expo.
 *
 * Mirrors the additive backend router `app/domains/series/router.py`, which
 * exposes a thin HTTP surface over the otherwise worker-only channel runner:
 * read a channel's run history / pacing and trigger a render or publish-pacing
 * pass. Every shape here mirrors the router's `_view` dicts / result summaries
 * exactly. Follows the Wave-1 lib client pattern (templates.ts / trends.ts).
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

/** One persisted runner pass (`channel_runs` row) — bookkeeping. */
export interface ChannelRunView {
  id: string;
  channel_id: string;
  user_id: string;
  /** Serialized `{ config, summary, run_id, idempotency_key }` (grows freely). */
  params: ChannelRunParams;
  created_at: string | null;
}

/** The `params` blob a run row stores: the config used + the outcome summary. */
export interface ChannelRunParams {
  config?: ChannelRunConfigView;
  summary?: RunSummary;
  run_id?: string;
  idempotency_key?: string;
  [key: string]: unknown;
}

/** Serialized `ChannelRunConfig` (mirrors `ChannelRunConfig.as_dict`). */
export interface ChannelRunConfigView {
  channel_id: string;
  user_id: string;
  hooks: string[];
  aspects: string[];
  accounts: string[];
  max_per_account: number | null;
  platforms: string[];
  voice_id: string | null;
  subject: string;
  template_slug: string;
  max_words: number;
}

/** `RunResult.summary()` — the outcome of one render pass. */
export interface RunSummary {
  planned: number;
  skipped_duplicates: number;
  paced_out: number;
  rendered: number;
  enqueue_failures: number;
}

/** `ScheduleResult.summary()` — the outcome of one publish-pacing pass. */
export interface ScheduleSummary {
  considered: number;
  scheduled: number;
}

/** One clip awaiting publish (`channel_clips` row view). */
export interface ChannelClipView {
  id: string;
  channel_id: string;
  run_id: string;
  spec_hash: string;
  job_id: string;
  account: string;
  platform: string;
  status: string;
  scheduled_publish_id: string | null;
  created_at: string | null;
}

/** `GET /series/channels/{id}/pending` payload: pending clips + render pacing. */
export interface ChannelPacing {
  pending: ChannelClipView[];
  /** Per-account count of non-failed clips rendered TODAY (UTC). */
  rendered_today: Record<string, number>;
}

/** One inline source row expanded into a narration script by the runner. */
export interface SourceItemInput {
  title?: string;
  url?: string;
  body?: string;
}

/** Body for `POST /series/channels/{id}/run` (mirrors `RunChannelRequest`). */
export interface RunChannelInput {
  source_items?: SourceItemInput[];
  hooks?: string[];
  aspects?: string[];
  accounts?: string[];
  platforms?: string[];
  subject?: string;
  voice_id?: string | null;
  template_slug?: string;
  max_words?: number | null;
  max_per_account?: number | null;
}

/** Body for `POST /series/channels/{id}/schedule` (mirrors `ScheduleChannelRequest`). */
export interface ScheduleChannelInput {
  platforms?: string[];
  accounts?: string[];
}

/** Envelope for a triggered render pass. */
export interface TriggerRunResult {
  run_id: string;
  summary: RunSummary;
}

/** Envelope for a triggered publish-pacing pass. */
export interface TriggerScheduleResult {
  summary: ScheduleSummary;
}

/** Encode a path segment so channel/run ids can never break the URL. */
function seg(value: string): string {
  return encodeURIComponent(String(value ?? "").trim());
}

/** Clamp a list limit into the backend-accepted 1..200 range (default 50). */
function boundLimit(limit: number): number {
  return Math.max(1, Math.min(200, Math.trunc(limit) || 50));
}

/**
 * List a channel's persisted runner passes, newest first
 * (`GET /series/channels/{channel_id}/runs`).
 */
export function listChannelRuns(
  channelId: string,
  limit = 50,
  options?: RequestOptions,
): Promise<{ runs: ChannelRunView[] }> {
  return request<{ runs: ChannelRunView[] }>(
    `/series/channels/${seg(channelId)}/runs?limit=${boundLimit(limit)}`,
    { options },
  );
}

/** Fetch one persisted runner pass by id (`GET /series/runs/{run_id}`). */
export function getChannelRun(
  runId: string,
  options?: RequestOptions,
): Promise<ChannelRunView> {
  return request<ChannelRunView>(`/series/runs/${seg(runId)}`, { options });
}

/**
 * Fetch a channel's COMPLETE-but-unpublished clips + today's per-account render
 * counts (`GET /series/channels/{channel_id}/pending`).
 */
export function getChannelPacing(
  channelId: string,
  options?: RequestOptions,
): Promise<ChannelPacing> {
  return request<ChannelPacing>(
    `/series/channels/${seg(channelId)}/pending`,
    { options },
  );
}

/**
 * Trigger one render pass over an inline source list
 * (`POST /series/channels/{channel_id}/run`). The backend REQUIRES an
 * `Idempotency-Key` header, so callers MUST pass `options.idempotencyKey`.
 */
export function triggerChannelRun(
  channelId: string,
  input: RunChannelInput,
  options?: RequestOptions,
): Promise<TriggerRunResult> {
  return request<TriggerRunResult>(`/series/channels/${seg(channelId)}/run`, {
    method: "POST",
    body: {
      source_items: input.source_items ?? [],
      hooks: input.hooks ?? [],
      aspects: input.aspects ?? [],
      accounts: input.accounts ?? [],
      platforms: input.platforms ?? [],
      subject: input.subject ?? "",
      voice_id: input.voice_id ?? null,
      template_slug: input.template_slug ?? "",
      max_words: input.max_words ?? null,
      max_per_account: input.max_per_account ?? null,
    },
    options,
  });
}

/**
 * Trigger one publish-pacing pass over a channel's COMPLETE clips
 * (`POST /series/channels/{channel_id}/schedule`). The backend REQUIRES an
 * `Idempotency-Key` header, so callers MUST pass `options.idempotencyKey`.
 */
export function triggerChannelSchedule(
  channelId: string,
  input: ScheduleChannelInput = {},
  options?: RequestOptions,
): Promise<TriggerScheduleResult> {
  return request<TriggerScheduleResult>(
    `/series/channels/${seg(channelId)}/schedule`,
    {
      method: "POST",
      body: {
        platforms: input.platforms ?? [],
        accounts: input.accounts ?? [],
      },
      options,
    },
  );
}
