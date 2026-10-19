/**
 * Launch Kit API — wraps `/launch-kit/*` (apps/api
 * `domains/launch_kit/router.py`, Menivor Growth phase 3: first-100-users
 * tooling). Plain HTTP, the same transport every other web feature uses
 * (`apiRequest`) — MCP is a separate surface for agent/tool callers, not
 * the web client.
 *
 * Nothing here submits to a launch directory, posts to Reddit, or spends
 * backlink credits on its own: see each function's docstring and the
 * backend's own module docs for the guarantees this UI relies on.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type PlatformStatus = "not_started" | "submitted" | "live";
export type PlaybookStepStatus = "pending" | "done";
export type PainPointDraftStatus = "drafted" | "approved" | "dismissed";

export interface LaunchPlatform {
  readonly id: string;
  readonly name: string;
  readonly url: string;
  readonly categories: readonly string[];
  readonly note: string;
  readonly status: PlatformStatus;
  readonly submitted_at: string | null;
  readonly tracking_note: string;
}

export interface LaunchPlatformsOverview {
  readonly platforms: readonly LaunchPlatform[];
  readonly category: string;
  readonly product_name: string;
}

/** The curated directory catalog, with this product's submission state merged in when given. */
export function listLaunchPlatforms(
  input: { productName?: string; category?: string } = {},
  options?: RequestOptions,
) {
  const params = new URLSearchParams();
  if (input.productName) params.set("product_name", input.productName);
  if (input.category) params.set("category", input.category);
  const query = params.toString();
  return apiRequest<LaunchPlatformsOverview>(`/launch-kit/platforms${query ? `?${query}` : ""}`, { options });
}

/** Record what a human actually did on one directory. Never submits anything itself. */
export function setPlatformStatus(
  input: { productName: string; platformId: string; status: PlatformStatus; note?: string },
  options?: RequestOptions,
) {
  return apiRequest<LaunchPlatform>("/launch-kit/platforms/status", {
    method: "POST",
    body: {
      product_name: input.productName.trim(),
      platform_id: input.platformId,
      status: input.status,
      note: (input.note ?? "").trim(),
    },
    options,
  });
}

export interface PainPointThread {
  readonly thread_url: string;
  readonly thread_title: string;
  readonly snippet: string;
  readonly subreddit: string;
  readonly upvotes: number;
  readonly age_days: number;
  readonly draft_reply: string;
}

export interface PainPointSearchResult {
  readonly query: string;
  readonly threads: readonly PainPointThread[];
  readonly count: number;
  readonly note: string;
}

/**
 * Live, read-only Reddit search. Every result is saved server-side as a
 * drafted reply for a human to review — call {@link listPainPointDrafts}
 * afterwards to get each thread's draft id for approve/dismiss actions.
 * There is no "post" action: posting is always a human, on Reddit, by hand.
 */
export function searchPainPoints(
  input: { query: string; subreddits?: readonly string[]; productName?: string; limit?: number },
  options?: RequestOptions,
) {
  return apiRequest<PainPointSearchResult>("/launch-kit/pain-points/search", {
    method: "POST",
    body: {
      query: input.query.trim(),
      subreddits: (input.subreddits ?? []).map((s) => s.trim()).filter(Boolean),
      product_name: (input.productName ?? "").trim(),
      limit: input.limit ?? 10,
    },
    options,
  });
}

export interface PainPointDraft {
  readonly id: string;
  readonly product_name: string;
  readonly query: string;
  readonly subreddit: string;
  readonly thread_url: string;
  readonly thread_title: string;
  readonly snippet: string;
  readonly upvotes: number;
  readonly age_days: number;
  readonly draft_reply: string;
  readonly status: PainPointDraftStatus;
  readonly created_at: string | null;
}

/** Saved pain-point reply drafts, optionally filtered by status and/or product. */
export function listPainPointDrafts(
  input: { status?: PainPointDraftStatus; productName?: string } = {},
  options?: RequestOptions,
) {
  const params = new URLSearchParams();
  if (input.status) params.set("status", input.status);
  if (input.productName) params.set("product_name", input.productName);
  const query = params.toString();
  return apiRequest<{ drafts: readonly PainPointDraft[] }>(
    `/launch-kit/pain-points/drafts${query ? `?${query}` : ""}`,
    { options },
  );
}

/** Approve (ready to post, by a person) or dismiss a drafted reply. Never "posted". */
export function setPainPointDraftStatus(
  draftId: string,
  status: PainPointDraftStatus,
  options?: RequestOptions,
) {
  return apiRequest<PainPointDraft>(`/launch-kit/pain-points/drafts/${encodeURIComponent(draftId)}`, {
    method: "POST",
    body: { status },
    options,
  });
}

export interface Backlink {
  readonly source_domain: string;
  readonly target_url: string;
  readonly anchor: string;
  readonly rank: number | null;
}

export interface FallbackDirectory {
  readonly id: string;
  readonly name: string;
  readonly url: string;
}

export interface BacklinksResult {
  readonly domain: string;
  readonly live: boolean;
  readonly configured: boolean;
  readonly backlinks: readonly Backlink[];
  readonly fallback_directories: readonly FallbackDirectory[];
  readonly message: string;
}

/**
 * Competitor backlinks. Returns the free directory fallback by default; only
 * spends DataForSEO credits when a key is configured on the server AND the
 * caller explicitly passes `allowLive: true`.
 */
export function findCompetitorBacklinks(
  domain: string,
  allowLive = false,
  options?: RequestOptions,
) {
  const params = new URLSearchParams({ domain: domain.trim() });
  if (allowLive) params.set("allow_live", "true");
  return apiRequest<BacklinksResult>(`/launch-kit/backlinks?${params.toString()}`, { options });
}

export interface PlaybookStep {
  readonly key: string;
  readonly title: string;
  readonly detail: string;
  readonly status: PlaybookStepStatus;
  readonly note: string;
  readonly updated_at: string | null;
}

export interface LaunchChecklist {
  readonly product_name: string;
  readonly known_product: boolean;
  readonly steps: readonly PlaybookStep[];
  readonly done: number;
  readonly total: number;
  readonly platforms_submitted: readonly string[];
}

/** The 10-step distribution playbook checklist for one product. */
export function getLaunchChecklist(productName: string, options?: RequestOptions) {
  const params = new URLSearchParams({ product_name: productName.trim() });
  return apiRequest<LaunchChecklist>(`/launch-kit/checklist?${params.toString()}`, { options });
}

/** Mark one playbook step done/pending by hand. */
export function markPlaybookStep(
  input: { productName: string; stepKey: string; status: PlaybookStepStatus; note?: string },
  options?: RequestOptions,
) {
  return apiRequest<{ product_name: string; step_key: string; status: PlaybookStepStatus; note: string }>(
    "/launch-kit/checklist/step",
    {
      method: "POST",
      body: {
        product_name: input.productName.trim(),
        step_key: input.stepKey,
        status: input.status,
        note: (input.note ?? "").trim(),
      },
      options,
    },
  );
}
