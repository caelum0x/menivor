/**
 * Typed client for the captions server tools — Expo.
 *
 * Thin, DB-free endpoints over the pure caption/loop cores so the mobile Caption
 * Studio can score a hook, preview Hormozi 1-2-word grouping, resolve per-platform
 * safe-zones, find a seamless loop point, rank beat-cut nudges and build a
 * keyword-SEO caption — all without running a render. Mirrors the web review
 * screens; wraps `apps/api/app/domains/captions/router.py`.
 *
 * Endpoints:
 *   POST /captions/hook-score  → scoreHook
 *   POST /captions/hormozi     → hormoziGroups
 *   GET  /captions/safezones   → getSafezones
 *   POST /captions/loop-check  → checkLoop
 *   POST /captions/beat-fit    → beatFit
 *   POST /captions/seo         → seoCaption
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

// ---------------------------------------------------------------------------
// hook-score
// ---------------------------------------------------------------------------

/** First-3s signals (each 0..1) extracted by the client-side probe. */
export interface HookScoreBody {
  motion: number;
  text: number;
  audio_onset: number;
  early_cut: number;
  speech: number;
  face_or_subject: number;
  hook_end_s: number;
  /** Opening line — when the hook misses the gate, drives cold-open rewrites. */
  opening_line: string;
}

export type HookGrade = "viral" | "strong" | "weak" | "poor";

/** The six weighted first-3s signal keys (excludes hook_end_s / opening_line). */
export type HookSignalKey =
  | "motion"
  | "text"
  | "audio_onset"
  | "early_cut"
  | "speech"
  | "face_or_subject";

export interface HookSuggestion {
  shape: string;
  text: string;
  rationale: string;
}

export interface HookScoreResult {
  score: number;
  passes_gate: boolean;
  grade: HookGrade;
  subscores: Record<string, number>;
  reasons: string[];
  suggestions: HookSuggestion[];
}

/** The six weighted first-3s signals in display order (mirrors _WEIGHTS). */
export const HOOK_SIGNALS: ReadonlyArray<{
  key: HookSignalKey;
  label: string;
  weight: number;
  hint: string;
}> = [
  { key: "motion", label: "Motion", weight: 0.22, hint: "Visual motion energy (pattern interrupt)" },
  { key: "text", label: "Text", weight: 0.2, hint: "A bold on-screen text hook present early" },
  { key: "audio_onset", label: "Audio onset", weight: 0.18, hint: "Immediate audio hit — no dead air" },
  { key: "early_cut", label: "Early cut", weight: 0.15, hint: "A hard cut / scene change in-window" },
  { key: "speech", label: "Speech", weight: 0.15, hint: "Spoken-word density — a verbal hook" },
  { key: "face_or_subject", label: "Subject", weight: 0.1, hint: "A clear subject / face on screen" },
];

export function scoreHook(
  body: HookScoreBody,
  options?: RequestOptions,
): Promise<HookScoreResult> {
  return request<HookScoreResult>("/captions/hook-score", {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// hormozi
// ---------------------------------------------------------------------------

export interface WordIn {
  text: string;
  start: number;
  end: number;
}

export interface HormoziBody {
  words: WordIn[];
  max_per_group: number;
  highlight_hex: string;
}

export interface HormoziStyleParams {
  font: string;
  all_caps: boolean;
  highlight_hex: string;
  base_hex: string;
  outline: number;
  shadow: number;
  max_per_group: number;
}

export interface HormoziGroup {
  text: string;
  words: string[];
  start: number;
  end: number;
  /** Index within `words` to accent; -1 = none. */
  highlight_index: number;
}

export interface HormoziResult {
  style: HormoziStyleParams;
  groups: HormoziGroup[];
}

export function hormoziGroups(
  body: HormoziBody,
  options?: RequestOptions,
): Promise<HormoziResult> {
  return request<HormoziResult>("/captions/hormozi", {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// safezones
// ---------------------------------------------------------------------------

export interface SafeZone {
  fontsize: number;
  margin_v: number;
  y_frac: number;
}

export interface SafezonesResult {
  play_h: number;
  safezones: Record<string, SafeZone>;
}

export function getSafezones(
  playH: number,
  options?: RequestOptions,
): Promise<SafezonesResult> {
  const query = `?play_h=${encodeURIComponent(String(Math.round(playH)))}`;
  return request<SafezonesResult>(`/captions/safezones${query}`, { options });
}

// ---------------------------------------------------------------------------
// loop-check
// ---------------------------------------------------------------------------

export interface LoopCheckBody {
  discontinuities: number[];
  fps: number;
  target_s?: number;
  min_s: number;
  max_s?: number;
  max_discontinuity?: number;
}

export interface LoopCheckResult {
  end_frame: number;
  end_s: number;
  discontinuity: number;
  accepted: boolean;
  reason: string;
}

export function checkLoop(
  body: LoopCheckBody,
  options?: RequestOptions,
): Promise<LoopCheckResult> {
  return request<LoopCheckResult>("/captions/loop-check", {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// beat-fit
// ---------------------------------------------------------------------------

export interface BeatFitBody {
  cuts: number[];
  beats: number[];
  fps: number;
}

/** `{ nudge_frames (as string) → mean_abs_error_seconds }`; lower is tighter. */
export interface BeatFitResult {
  fits: Record<string, number>;
}

export function beatFit(
  body: BeatFitBody,
  options?: RequestOptions,
): Promise<BeatFitResult> {
  return request<BeatFitResult>("/captions/beat-fit", {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// seo
// ---------------------------------------------------------------------------

export interface SeoBody {
  text: string;
  platform: string;
  base_caption: string;
}

export interface SeoResult {
  caption: string;
  hashtags: string[];
  keywords: string[];
}

export function seoCaption(
  body: SeoBody,
  options?: RequestOptions,
): Promise<SeoResult> {
  return request<SeoResult>("/captions/seo", { method: "POST", body, options });
}

// ---------------------------------------------------------------------------
// Platforms shared across the studio (safezones + SEO share these surfaces)
// ---------------------------------------------------------------------------

export const CAPTION_PLATFORMS: ReadonlyArray<{ id: string; label: string }> = [
  { id: "tiktok", label: "TikTok" },
  { id: "reels", label: "Reels" },
  { id: "shorts", label: "Shorts" },
  { id: "x", label: "X" },
];

/** Common playback heights for the safe-zone preview, tallest first. */
export const PLAY_HEIGHTS: ReadonlyArray<{ value: number; label: string }> = [
  { value: 2340, label: "2340p" },
  { value: 1920, label: "1920p" },
  { value: 1280, label: "1280p" },
];
