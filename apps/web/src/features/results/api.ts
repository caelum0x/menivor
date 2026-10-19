/** Results page API — wraps /me/results and /me/tracked-posts. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type PostState = "tracking" | "waiting" | "needs_access" | "no_stats" | "done";

export interface ResultsPlatform {
  readonly platform: string;
  readonly label: string;
  readonly connected: boolean;
  readonly reads_numbers: boolean;
  readonly needs_reconnect: boolean;
  /** Native connections reconnect straight from this page; others go to Connections. */
  readonly reconnect_here: boolean;
  /** False when this server cannot start that connection (no OAuth app set up). */
  readonly can_connect?: boolean;
  readonly note: string;
}

export interface Remake {
  readonly q: string;
  readonly preset: string;
}

export interface RankedHook {
  readonly hook: string;
  readonly posts: number;
  readonly views: number | null;
  readonly avg_views: number | null;
  readonly engagements: number;
  readonly engagement_rate: number | null;
  readonly remake: Remake;
}

export interface RankedStyle extends Omit<RankedHook, "hook"> {
  readonly preset: string;
}

export interface Winner extends RankedHook {
  readonly why: string;
}

export interface TrackedPost {
  readonly id: string;
  readonly platform: string;
  readonly label: string;
  readonly url: string;
  readonly title: string;
  readonly from_menivor: boolean;
  readonly state: PostState;
  readonly note: string;
  readonly views: number | null;
  readonly likes: number | null;
  readonly comments: number | null;
  readonly shares: number | null;
  readonly saves: number | null;
  readonly last_checked_at: string | null;
  readonly can_type_numbers: boolean;
}

export interface SeriesPoint {
  readonly date: string;
  readonly views: number;
}

export interface Results {
  readonly has_data: boolean;
  readonly tracking: number;
  readonly totals: { readonly posts: number; readonly views: number | null; readonly engagements: number };
  readonly winner: Winner | null;
  readonly hooks: readonly RankedHook[];
  readonly styles: readonly RankedStyle[];
  readonly series: readonly SeriesPoint[];
  readonly posts: readonly TrackedPost[];
  readonly platforms: readonly ResultsPlatform[];
}

export interface TypedNumbers {
  readonly views?: number;
  readonly likes?: number;
  readonly comments?: number;
  readonly shares?: number;
  readonly saves?: number;
}

const EMPTY: Results = {
  has_data: false,
  tracking: 0,
  totals: { posts: 0, views: null, engagements: 0 },
  winner: null,
  hooks: [],
  styles: [],
  series: [],
  posts: [],
  platforms: [],
};

/** Fill any field an older API omits so the page never reads `undefined`. */
export function normalizeResults(raw: Partial<Results> | null | undefined): Results {
  const data = raw ?? {};
  return {
    ...EMPTY,
    ...data,
    totals: { ...EMPTY.totals, ...(data.totals ?? {}) },
    hooks: data.hooks ?? [],
    styles: data.styles ?? [],
    series: data.series ?? [],
    posts: data.posts ?? [],
    platforms: data.platforms ?? [],
  };
}

export async function getResults(options?: RequestOptions): Promise<Results> {
  return normalizeResults(await apiRequest<Partial<Results>>("/me/results", { options }));
}

/** Read the numbers of the caller's posts now (rate limited server-side). */
export async function syncResults(options?: RequestOptions): Promise<Results> {
  return normalizeResults(
    await apiRequest<Partial<Results>>("/me/results/sync", { method: "POST", options }),
  );
}

export async function trackPostLink(url: string, options?: RequestOptions): Promise<Results> {
  return normalizeResults(
    await apiRequest<Partial<Results>>("/me/tracked-posts", {
      method: "POST",
      body: { url: url.trim().slice(0, 2048) },
      options,
    }),
  );
}

export async function typePostNumbers(
  postId: string,
  numbers: TypedNumbers,
  options?: RequestOptions,
): Promise<Results> {
  return normalizeResults(
    await apiRequest<Partial<Results>>(
      `/me/tracked-posts/${encodeURIComponent(postId)}/numbers`,
      { method: "POST", body: numbers, options },
    ),
  );
}

export async function untrackPost(postId: string, options?: RequestOptions): Promise<Results> {
  return normalizeResults(
    await apiRequest<Partial<Results>>(`/me/tracked-posts/${encodeURIComponent(postId)}`, {
      method: "DELETE",
      options,
    }),
  );
}
