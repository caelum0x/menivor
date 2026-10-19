/**
 * Typed client for 1-body/N-hooks retention A/B experiments — Expo. Hold the
 * body/caption/sound constant, vary ONLY the hook across N variants, feed each
 * variant's real retention metrics back in, and let the SERVER compute the
 * retention-weighted winner. Mirrors the web `channel-console/api.ts` experiment
 * calls and targets the REAL publishing-experiments routes:
 *
 *   POST /experiments                                     create (key, N hooks, body_ref)
 *   GET  /experiments/{key}                               experiment + variants + verdict
 *   POST /experiments/{key}/variants/{id}/metrics         ingest a variant's retention snapshot
 *   POST /experiments/{key}/evaluate                      persist + return the winner
 *
 * Distinct from the pure-client `ab-lab` / `retention-lab` screens, which only
 * run `@reelforge/growth-analytics` locally and submit nothing — this client is
 * the first server-persisted experiment surface on mobile. `fetch` is mocked
 * only in tests; product code always talks to the real API.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

/** Number of hook variants a single experiment may hold (backend-enforced). */
export const MIN_HOOKS = 2;
export const MAX_HOOKS = 20;

/** Body for `POST /experiments` — one body ref, N (2..20) hook variants. */
export interface CreateExperimentBody {
  experiment_key: string;
  hook_refs: string[];
  body_ref?: string;
}

/** Retention snapshot for one variant (`POST .../variants/{id}/metrics`). All
 * ratio fields are 0..1; `views` is a non-negative integer. `completion_rate`
 * and `rewatch_rate` are `null` when the platform did not report them ("not
 * measured"), which the server keeps distinct from 0. */
export interface MetricsBody {
  views: number;
  completion_rate: number | null;
  avg_watch_frac: number;
  rewatch_rate: number | null;
  engagement_rate: number;
}

/** One hook arm of an experiment with its accumulated retention metrics. */
export interface ExperimentVariant {
  id: string;
  hook_ref: string;
  views: number;
  /** null = not measured (no platform reported it). */
  completion_rate: number | null;
  avg_watch_frac: number;
  /** null = not measured (no platform reported it). */
  rewatch_rate: number | null;
  engagement_rate: number;
}

/** An experiment with its persisted hook variants and (once evaluated) verdict. */
export interface Experiment {
  id: string;
  experiment_key: string;
  /** `running` while collecting, `conclusive` once a winner is persisted. */
  status: string;
  body_ref: string;
  winner_variant_id: string | null;
  winner_hook_ref: string | null;
  variants: ExperimentVariant[];
}

/** The partial variant echoed back by the metrics-ingest endpoint. */
export interface MetricsIngestResult {
  id: string;
  hook_ref: string;
  views: number;
}

/**
 * POST /experiments — create a 1-body/N-hooks retention experiment. `hook_refs`
 * must hold between {@link MIN_HOOKS} and {@link MAX_HOOKS} entries (the backend
 * rejects out-of-range with 422). Pass `options.idempotencyKey` so an ambiguous
 * transport retry never double-creates.
 */
export function createExperiment(
  body: CreateExperimentBody,
  options?: RequestOptions,
): Promise<Experiment> {
  return request<Experiment>("/experiments", {
    method: "POST",
    body,
    options,
  });
}

/**
 * GET /experiments/{key} — the experiment, its variants and current verdict.
 * A missing/foreign key yields a 404 → {@link ApiError}. Owner-scoped server-side.
 */
export function getExperiment(
  experimentKey: string,
  options?: RequestOptions,
): Promise<Experiment> {
  return request<Experiment>(
    `/experiments/${encodeURIComponent(experimentKey)}`,
    { options },
  );
}

/**
 * POST /experiments/{key}/variants/{id}/metrics — ingest one variant's retention
 * snapshot (overwrites the variant's accumulated metrics). Returns the touched
 * variant's `{ id, hook_ref, views }`. An unknown key/variant yields 404.
 */
export function ingestMetrics(
  experimentKey: string,
  variantId: string,
  body: MetricsBody,
  options?: RequestOptions,
): Promise<MetricsIngestResult> {
  return request<MetricsIngestResult>(
    `/experiments/${encodeURIComponent(experimentKey)}/variants/${encodeURIComponent(
      variantId,
    )}/metrics`,
    { method: "POST", body, options },
  );
}

/**
 * POST /experiments/{key}/evaluate — run the retention-weighted winner selection
 * server-side, PERSIST the verdict, and return the refreshed experiment. When the
 * sample is inconclusive (too few views, or a near-tie) the winner fields stay
 * null and `status` remains open.
 */
export function evaluateExperiment(
  experimentKey: string,
  options?: RequestOptions,
): Promise<Experiment> {
  return request<Experiment>(
    `/experiments/${encodeURIComponent(experimentKey)}/evaluate`,
    { method: "POST", options },
  );
}

/**
 * Parse a free-text hook list (one hook per line, blank lines skipped) into the
 * `hook_refs` array. Trims each line; preserves order and de-dupes exact repeats.
 */
export function parseHookRefs(text: string): string[] {
  const seen = new Set<string>();
  const refs: string[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.length > 0 && !seen.has(trimmed)) {
      seen.add(trimmed);
      refs.push(trimmed);
    }
  }
  return refs;
}
