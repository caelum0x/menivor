/**
 * Ad Clone API (signed in, ADCLONE_ENABLED on the server). Step 1 turns a winning ad link into
 * a clone brief (structure only), step 3 writes our own versions as episode plans priced per
 * render engine. Rendering from the web is a dry run; nothing here spends.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";

export type AdCloneAspect = "9:16" | "16:9";
export type AdCloneLanguage = "original" | "en" | "tr" | "de" | "es" | "fr" | "ar";

export interface AdCloneBeat {
  readonly index: number;
  readonly start_s: number;
  readonly end_s: number;
  readonly shot_type: string;
  readonly framing: string;
  readonly camera_move: string;
  readonly speaker: string;
  readonly line: string;
  readonly on_screen_text: string;
  readonly role: string;
}

export interface AdCloneBrief {
  readonly version: 1;
  readonly source: {
    readonly url: string;
    readonly platform: string;
    readonly source_ref: string;
    readonly duration_s: number;
    readonly width: number;
    readonly height: number;
    readonly language: string;
    readonly avoid_terms: readonly string[];
  };
  readonly hook: { readonly end_s: number; readonly pattern: string; readonly summary: string; readonly framing: string };
  readonly beats: readonly AdCloneBeat[];
  readonly pacing: {
    readonly shot_count: number;
    readonly avg_shot_s: number;
    readonly cuts_per_10s: number;
    readonly beat_count: number;
    readonly avg_beat_s: number;
    readonly music_bpm: number | null;
    readonly onsets_s: readonly number[];
  };
  readonly caption_style: {
    readonly present: boolean;
    readonly position: string;
    readonly case: string;
    readonly words_per_caption: number;
    readonly burned_in: boolean;
  };
  readonly transcript: string;
  readonly setting: string;
  readonly keeps: readonly string[];
  readonly analysis: "heuristic" | "llm";
  readonly notes: readonly string[];
}

export interface AdCloneProduct {
  readonly id: string;
  readonly product: string;
  readonly brand_name: string;
  readonly domain: string;
  readonly cta: string;
  readonly end_card: string;
  readonly characters: readonly { readonly key: string; readonly name: string; readonly role: string; readonly persona: string; readonly voice_locked: boolean }[];
}

export interface AdCloneEstimate {
  readonly engine: string;
  readonly label: string;
  readonly configured: boolean;
  readonly usd: number;
  readonly source: string;
  readonly keys: readonly string[];
  /** "list" = the provider's published price; "estimate" = not confirmed from an official price page. */
  readonly price_basis?: "list" | "estimate";
}

export interface AdClonePlanLine {
  readonly id: string;
  readonly speaker: string;
  readonly text: string;
}

export interface AdClonePlan {
  readonly episode: number;
  readonly slug: string;
  readonly aspect: AdCloneAspect;
  readonly language: string;
  readonly lines: readonly AdClonePlanLine[];
  readonly shots: readonly { readonly id: string; readonly kind: string; readonly dur: number; readonly lines: readonly string[] }[];
  readonly stills: readonly { readonly id: string }[];
  readonly edit: readonly Record<string, unknown>[];
  readonly clone: {
    readonly variation: string;
    readonly writer: string;
    readonly hook_pattern: string;
    readonly writer_note?: string;
  };
}

export interface AdCloneVariation {
  readonly plan: AdClonePlan;
  readonly estimates: readonly AdCloneEstimate[];
  readonly engine: AdCloneEstimate & { readonly dry_run_only: boolean; readonly reason: string };
  /** AI-video credits held when this version is approved for a paid render. */
  readonly ai_video_credits: number;
  readonly midjourney: readonly { readonly still: string; readonly save_as: string; readonly prompt_v7: string }[];
}

export interface AdCloneResult {
  readonly brief: AdCloneBrief;
  readonly product: AdCloneProduct;
  readonly variations: readonly AdCloneVariation[];
  readonly voice: { readonly engine: string; readonly label: string };
  /** False while the owner keeps paid rendering switched off on the server. */
  readonly paid_render: boolean;
}

export interface AdCloneSettings {
  readonly product: string;
  readonly aspect: AdCloneAspect;
  readonly variations: 1 | 2 | 3;
  readonly language: AdCloneLanguage;
}

export function listProducts(options?: RequestOptions): Promise<{ readonly products: readonly AdCloneProduct[] }> {
  return apiRequest("/ad-clone/products", { options });
}

export function makeBrief(url: string, options?: RequestOptions): Promise<{ readonly brief: AdCloneBrief }> {
  return apiRequest("/ad-clone/brief", { method: "POST", body: { url }, options });
}

export function makeClone(brief: AdCloneBrief, settings: AdCloneSettings, options?: RequestOptions): Promise<AdCloneResult> {
  return apiRequest("/ad-clone/plan", { method: "POST", body: { brief, ...settings }, options });
}

export function dryRun(plan: AdClonePlan, engine: string, options?: RequestOptions): Promise<{ readonly requests: readonly unknown[]; readonly dry_run: boolean }> {
  return apiRequest("/ad-clone/render", { method: "POST", body: { plan, engine, dry_run: true }, options });
}

export interface AdCloneRenderStarted {
  readonly job_id: string;
  readonly state: number;
  readonly project_id: string;
  readonly ai_video_credits: number;
  readonly replayed?: boolean;
}

export interface AdCloneRenderJob {
  readonly job_id: string;
  readonly state: number;
  readonly stage: string;
  readonly engine: string;
  readonly quoted_usd: number;
  readonly spent_usd: number;
  readonly project_id: string;
  readonly video_url: string;
  readonly poster_url: string;
  readonly error: string;
}

export const RENDER_DONE = 1;
export const RENDER_FAILED = -1;

/** Approve a paid render. The same idempotency key on a retry replays the same job (never pays twice). */
export function approveRender(
  plan: AdClonePlan,
  engine: string,
  quotedCredits: number,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<AdCloneRenderStarted> {
  return apiRequest("/ad-clone/render/approve", {
    method: "POST",
    body: { plan, engine, quoted_credits: quotedCredits },
    options: { ...options, idempotencyKey },
  });
}

export function getRender(jobId: string, options?: RequestOptions): Promise<AdCloneRenderJob> {
  const id = encodeURIComponent(jobId);
  return apiRequest(`/ad-clone/render/${id}`, { options });
}

export type AdCloneFailure =
  | { readonly kind: "ip_guard"; readonly problems: readonly string[] }
  | { readonly kind: "off" }
  | { readonly kind: "credits" }
  | { readonly kind: "link"; readonly message: string }
  | { readonly kind: "other" };

/** Map an API error to the cases this flow explains differently. */
export function classifyAdCloneFailure(err: unknown): AdCloneFailure {
  if (!(err instanceof ApiError)) return { kind: "other" };
  const detail = err.detail as { data?: { code?: unknown; problems?: unknown }; message?: unknown } | undefined;
  const data = detail && typeof detail === "object" ? detail.data : undefined;
  if (err.status === 422 && data?.code === "ip_guard") {
    const problems = Array.isArray(data.problems) ? data.problems.filter((p): p is string => typeof p === "string") : [];
    return { kind: "ip_guard", problems };
  }
  if (err.status === 403) return { kind: "off" };
  if (err.status === 402) return { kind: "credits" };
  if (err.status === 422 || err.status === 400) {
    const raw = typeof detail?.message === "string" ? detail.message : err.message;
    return { kind: "link", message: raw.replace(/^[^:]*:\s*/, "") };
  }
  return { kind: "other" };
}
