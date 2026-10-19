/**
 * Typed client for trend scoring — Expo. Submit observed usage-count series and
 * get opportunity-ranked trends to build to before they peak. Mirrors the web
 * `src/features/trends/api.ts`.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface TrendIn {
  trend_id: string;
  kind?: string;
  counts: number[];
}

export interface ScoredTrend {
  trend_id: string;
  velocity: number;
  acceleration: number;
  saturation: number;
  opportunity: number;
  phase: string;
  recommend: boolean;
}

/**
 * A trend persisted in the durable recommended feed. Returned by
 * `GET /trends/recommended` and `POST /trends/observe` (the backend scores the
 * observed series, so `opportunity`/`saturation` are already 0..1 ratios).
 */
export interface ObservedTrend {
  id: string;
  trend_id: string;
  kind: string;
  label: string;
  opportunity: number;
  saturation: number;
  phase: string;
  recommend: boolean;
}

export function rankTrends(
  trends: TrendIn[],
  options?: RequestOptions,
): Promise<{ trends: ScoredTrend[] }> {
  return request<{ trends: ScoredTrend[] }>("/trends/rank", {
    method: "POST",
    body: { trends, limit: 20 },
    options,
  });
}

/**
 * The durable trends feed: highest-opportunity, recommended (rising, not-peaked)
 * trends first. Backs the default pull-to-refresh list on the Trends Feed.
 */
export function getRecommendedTrends(
  limit = 20,
  options?: RequestOptions,
): Promise<{ trends: ObservedTrend[] }> {
  const bounded = Math.max(1, Math.min(100, Math.trunc(limit) || 20));
  return request<{ trends: ObservedTrend[] }>(
    `/trends/recommended?limit=${bounded}`,
    { options },
  );
}

/**
 * Score + persist observed usage series into the durable recommended feed
 * (append-only). Returns the freshly-scored rows so the caller can reconcile the
 * feed without a second round-trip.
 */
export function observeTrends(
  trends: TrendIn[],
  options?: RequestOptions,
): Promise<{ observed: ObservedTrend[] }> {
  return request<{ observed: ObservedTrend[] }>("/trends/observe", {
    method: "POST",
    body: { trends, limit: 20 },
    options,
  });
}

/**
 * The consent dimension (append-only, GDPR/ToS) that MUST be granted before the
 * backend will enqueue a scrape. Mirrors `trends/providers/consent.CONSENT_KIND`.
 * Grant it with `recordConsent(TREND_SCRAPING_CONSENT_KIND, true)` from
 * `@/lib/compliance`.
 */
export const TREND_SCRAPING_CONSENT_KIND = "trend_scraping";

/** The kinds of source a pull can target. `trending` pulls the For-You feed. */
export type PullKind = "hashtag" | "sound" | "trending";

/** Request body for `POST /trends/pull` (mirrors the backend `PullBody`). */
export interface PullTrendInput {
  /** Hashtag/sound to scrape. Ignored (sent as `trending`) when kind=trending. */
  target: string;
  kind: PullKind;
  /** Posts to sample, 1..500 (backend default 50). */
  max_posts: number;
}

/**
 * The accepted-pull envelope returned by `POST /trends/pull`: the scrape runs on
 * the worker, so this only confirms the job was enqueued. Poll `GET /jobs/{id}`
 * with {@link getJob} until terminal, then reload {@link getRecommendedTrends}.
 */
export interface PullTrendResult {
  job_id: string;
  target: string;
  kind: string;
  state: string;
}

/**
 * Enqueue a ToS-gated trend scrape into the durable recommended feed. The
 * backend enforces the consent + allowlist gate, debits the pull cost, and
 * enqueues a worker job; it returns immediately with `state: "processing"`.
 *
 * Throws `ApiError` with a meaningful status: 403 (no consent / target not on
 * the allowlist), 402 (insufficient credits), or 503 (pull layer unavailable).
 */
export function pullTrend(
  input: PullTrendInput,
  options?: RequestOptions,
): Promise<PullTrendResult> {
  const kind: PullKind = input.kind;
  const target =
    kind === "trending" ? "trending" : input.target.trim().replace(/^#+/, "");
  const maxPosts = Math.max(1, Math.min(500, Math.trunc(input.max_posts) || 50));
  return request<PullTrendResult>("/trends/pull", {
    method: "POST",
    body: { target, kind, max_posts: maxPosts },
    options,
  });
}

/** Parse "id: 100,400,1200" lines into TrendIn[] (skips blanks/malformed). */
export function parseTrendLines(text: string): TrendIn[] {
  return text
    .split("\n")
    .map((line) => {
      const [rawId = "", rawCounts = ""] = line.split(":");
      // Drop empty segments before coercing: Number("") is 0, which would
      // turn a count-less line ("nope") or a stray comma into a phantom 0.
      const counts = rawCounts
        .split(",")
        .map((n) => n.trim())
        .filter((n) => n.length > 0)
        .map(Number)
        .filter((n) => Number.isFinite(n));
      return { trend_id: rawId.trim(), kind: "custom", counts };
    })
    .filter((t) => t.trend_id.length > 0 && t.counts.length > 0);
}
