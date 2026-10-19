/**
 * Keyword tracker API — wraps `/keyword-tracker` (apps/api
 * `domains/keyword_tracker/router.py`, Menivor Growth phase 2).
 *
 * App Store only: the Google Play Developer API has no public keyword-rank
 * endpoint. A daily server-side job keeps every tracked keyword's rank
 * current; this client only reads the result and adds/removes keywords.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface HistoryPoint {
  readonly date: string;
  readonly position: number | null;
}

export interface TrackedKeyword {
  readonly id: string;
  readonly app_id: string;
  readonly app_name: string;
  readonly country: string;
  readonly term: string;
  /** Current top-50 rank, or `null` when the app is not in the top 50. */
  readonly current_rank: number | null;
  readonly checked_count: number;
  readonly last_checked_at: string | null;
  readonly last_error: string;
  /** Positive = improved (a lower rank number) over the window; `null` with no baseline yet. */
  readonly change_7d: number | null;
  readonly change_30d: number | null;
  readonly history: readonly HistoryPoint[];
  /**
   * Apple's own Search Popularity index (5-100 in steps of 5). `null` until a
   * connected Apple Search Ads account has scored it — see
   * `apple_ads_connected` below for whether one is connected at all. Apple
   * does not publish a separate "difficulty" number alongside it.
   */
  readonly popularity: number | null;
}

export interface KeywordTrackerOverview {
  readonly keywords: readonly TrackedKeyword[];
  readonly limit: number;
  readonly paid: boolean;
  /** Whether the caller's scope has a connected Apple Search Ads account. */
  readonly apple_ads_connected: boolean;
}

export function listKeywords(workspaceId?: string, options?: RequestOptions) {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return apiRequest<KeywordTrackerOverview>(`/keyword-tracker${query}`, { options });
}

export function addKeyword(
  input: { appId: string; term: string; appName?: string; country?: string },
  options?: RequestOptions,
) {
  return apiRequest<TrackedKeyword>("/keyword-tracker", {
    method: "POST",
    body: {
      app_id: input.appId.trim(),
      term: input.term.trim(),
      app_name: (input.appName ?? "").trim(),
      country: (input.country ?? "us").trim().toLowerCase() || "us",
    },
    options,
  });
}

export function removeKeyword(keywordId: string, options?: RequestOptions) {
  return apiRequest<{ removed: boolean }>(`/keyword-tracker/${encodeURIComponent(keywordId)}`, {
    method: "DELETE",
    options,
  });
}

export function refreshKeyword(keywordId: string, options?: RequestOptions) {
  return apiRequest<TrackedKeyword>(`/keyword-tracker/${encodeURIComponent(keywordId)}/refresh`, {
    method: "POST",
    options,
  });
}
