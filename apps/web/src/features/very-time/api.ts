/**
 * "Very ___ Time" one-click template API. Signed in. The plan writes the five
 * beats and prices both versions; starting sends the same inputs plus the
 * price the user saw, so a changed price is refused (409), never charged.
 * Progress and the finished video come from the shared story8 job route.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";
import { getStory, type StoryJob, type StoryMode, type StoryPrice } from "@/src/features/story8/api";

export type VeryTimeLook = "console" | "flash" | "atelier";
export type VeryTimeMode = StoryMode;
export type VeryTimePrice = StoryPrice;
export type VeryTimePayoff = "native" | "lipsync" | "voiceover";
export type VeryTimeEngine = "free" | "eleven_v3";
export type VeryTimeDelivery = "deadpan" | "quiet" | "tired" | "warm";
export type VeryTimeChestStatus = "ok" | "rerolled" | "overlay" | "unchecked";

export interface VeryTimeChest {
  readonly index: number;
  readonly status: VeryTimeChestStatus;
  readonly attempts: number;
}

export type VeryTimeJob = StoryJob & {
  readonly refunded?: boolean | Readonly<Record<string, number>>;
  readonly sheet_url?: string | null;
  readonly chest?: readonly VeryTimeChest[];
  readonly payoff_used?: VeryTimePayoff;
  readonly take_key?: string;
  readonly duration_s?: VeryTimeDuration;
};

export type VeryTimeDuration = 10 | 15 | 30;
export type VeryTimeBrandPreset = "oxhan" | "custom";

export interface VeryTimeEndCard {
  readonly cta: string;
  readonly logo: boolean;
  readonly seconds: number;
}

export interface VeryTimeBrand {
  /** "oxhan" is the built-in Oxhan Atelier brand; the server fills garment, chest, host, line, CTA and logo. */
  readonly preset?: VeryTimeBrandPreset;
  /** Shown on the end card, 60 characters at most. */
  readonly cta?: string;
  /** An "uploads/..." key: the logo on the end card. */
  readonly logo_ref?: string;
  readonly garment?: string;
  readonly chest_text?: string;
  /** An "uploads/..." key from presignAndUpload: the garment photo used as a reference. */
  readonly garment_ref?: string;
}

export interface VeryTimeVoice {
  readonly engine: VeryTimeEngine;
  readonly delivery?: VeryTimeDelivery;
  readonly take_key?: string;
  readonly reply_line?: string;
}

export interface VeryTimeSound {
  readonly sfx: boolean;
  readonly room_tone: boolean;
}

export interface VeryTimeInput {
  readonly place_word: string;
  readonly ritual: string;
  readonly look: VeryTimeLook;
  readonly line?: string;
  readonly character_id?: string;
  readonly brand?: VeryTimeBrand;
  readonly language?: string;
  readonly voice?: VeryTimeVoice;
  readonly sound?: VeryTimeSound;
  readonly payoff?: VeryTimePayoff;
  /** 10, 15 or 30 seconds; omitted means 15. */
  readonly duration_s?: VeryTimeDuration;
}

export interface VeryTimeBeat {
  readonly index: number;
  readonly beat: string;
  readonly line: string;
  readonly camera: string;
  readonly seconds: number;
}

export interface VeryTimePlan {
  readonly preset: string;
  readonly look: VeryTimeLook;
  readonly caption_style: string;
  readonly duration_s?: VeryTimeDuration;
  readonly brand_preset?: string;
  readonly end_card?: VeryTimeEndCard;
  readonly lines: readonly string[];
  readonly beats: readonly VeryTimeBeat[];
  readonly quote: {
    readonly seconds: number;
    readonly frames: VeryTimePrice;
    readonly animated: VeryTimePrice;
    /** Already included in frames/animated standard credits. */
    readonly extras?: { readonly voice_credits: number; readonly sfx_credits: number };
  };
}

export interface VeryTimeTakesInput {
  readonly place_word: string;
  readonly line?: string;
  readonly reply_line?: string;
  readonly engine: VeryTimeEngine;
  readonly delivery: VeryTimeDelivery;
  readonly language?: string;
  readonly count?: 2 | 3;
}

export interface VeryTimeTake {
  readonly key: string;
  readonly url: string;
  readonly seconds: number;
  readonly flatness: number;
}

export interface VeryTimeTakes {
  readonly takes: readonly VeryTimeTake[];
  readonly recommended: string;
}

export interface VeryTimeStarted {
  readonly job_id: string;
  readonly state: number;
}

export function planVeryTime(body: VeryTimeInput, options?: RequestOptions): Promise<VeryTimePlan> {
  return apiRequest<VeryTimePlan>("/film/very-time/plan", { method: "POST", body, options });
}

export function startVeryTime(
  body: VeryTimeInput & { readonly mode: VeryTimeMode; readonly quoted: VeryTimePrice },
  options?: RequestOptions,
): Promise<VeryTimeStarted> {
  return apiRequest<VeryTimeStarted>("/film/very-time", { method: "POST", body, options });
}

/** Two or three takes of the line to listen to; the flattest is recommended. */
export function makeTakes(body: VeryTimeTakesInput, options?: RequestOptions): Promise<VeryTimeTakes> {
  return apiRequest<VeryTimeTakes>("/film/very-time/takes", { method: "POST", body, options });
}

export function getVeryTimeJob(jobId: string, options?: RequestOptions): Promise<VeryTimeJob> {
  return getStory(jobId, options);
}

/** What the screen should do about a failed request. */
export type VeryTimeFailure =
  | { readonly kind: "guard"; readonly terms: readonly string[] }
  | { readonly kind: "quote_changed" }
  | { readonly kind: "credits"; readonly aiVideo: boolean }
  | { readonly kind: "rate_limited" }
  | { readonly kind: "voice_unavailable" }
  | { readonly kind: "other" };

function errorData(err: ApiError): { code?: unknown; terms?: unknown } {
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return {};
  const data = (detail as { data?: unknown }).data;
  return data && typeof data === "object" ? (data as { code?: unknown; terms?: unknown }) : {};
}

/** Map an API error to the few cases this flow treats specially. */
export function classifyFailure(err: unknown): VeryTimeFailure {
  if (!(err instanceof ApiError)) return { kind: "other" };
  const { code, terms } = errorData(err);
  if (err.status === 400 && code === "guard_blocked") {
    const words = Array.isArray(terms) ? terms.filter((t): t is string => typeof t === "string" && t.trim() !== "") : [];
    return { kind: "guard", terms: words };
  }
  if (err.status === 409 && code === "quote_changed") return { kind: "quote_changed" };
  if (err.status === 402) return { kind: "credits", aiVideo: code === "ai_video_credits_required" };
  if (err.status === 429) return { kind: "rate_limited" };
  if (err.status === 503 && code === "voice_unavailable") return { kind: "voice_unavailable" };
  return { kind: "other" };
}
