/** Pure helpers for the Ad Clone screens (no React, no network). */

import type { AdCloneBrief, AdCloneEstimate, AdCloneLanguage, AdCloneSettings } from "./api";

export const DEFAULT_SETTINGS: AdCloneSettings = { product: "oxhan", aspect: "9:16", variations: 1, language: "original" };

export const LANGUAGES: readonly { readonly value: AdCloneLanguage; readonly label: string }[] = [
  { value: "original", label: "Same as the ad" },
  { value: "en", label: "English" },
  { value: "tr", label: "Turkish" },
  { value: "de", label: "German" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "ar", label: "Arabic" },
];

const SUPPORTED = /^(https?:\/\/)?([a-z0-9-]+\.)*(tiktok\.com|youtube\.com|youtu\.be|vimeo\.com|x\.com|twitter\.com)(\/|$)/i;

/** Why a pasted link cannot be used yet, or "" when it looks fine. */
export function linkProblem(raw: string): string {
  const url = raw.trim();
  if (!url) return "Paste the link of the ad you want to clone.";
  if (url.length > 500) return "That link is too long.";
  if (!SUPPORTED.test(url)) return "Use a TikTok, YouTube, Vimeo or X link.";
  return "";
}

const PATTERNS: Record<string, string> = {
  price_shock: "Price shock",
  question: "Question",
  pov: "POV",
  bold_claim: "Bold claim",
  list: "List",
  statement: "Statement",
};

export function hookLabel(pattern: string): string {
  return PATTERNS[pattern] ?? "Statement";
}

export function seconds(value: number): string {
  return `${value.toFixed(value < 10 ? 1 : 0)} s`;
}

/** The three facts the clone brief panel leads with. */
export function briefSummary(brief: AdCloneBrief): { readonly hook: string; readonly beats: string; readonly pacing: string } {
  const hookText = brief.beats[0]?.on_screen_text || brief.beats[0]?.line || "";
  return {
    hook: `${hookLabel(brief.hook.pattern)} in the first ${seconds(brief.hook.end_s)}${hookText ? `: "${hookText}"` : ""}`,
    beats: `${brief.pacing.beat_count} beats over ${brief.pacing.shot_count} shots`,
    pacing: `A cut every ${seconds(brief.pacing.avg_shot_s)}${brief.pacing.music_bpm ? `, music near ${Math.round(brief.pacing.music_bpm)} BPM` : ""}`,
  };
}

export function beatLabel(beat: { readonly role: string; readonly framing: string; readonly camera_move: string; readonly shot_type: string }): string {
  const move = beat.camera_move === "unknown" || beat.camera_move === "static" ? "" : `, ${beat.camera_move.replace("_", " ")}`;
  const kind = beat.shot_type.replace("_", " ");
  return `${beat.role || "beat"}: ${beat.framing} ${kind}${move}`;
}

export function usd(value: number): string {
  return `$${value.toFixed(2)}`;
}

/** Cheapest first; the chosen engine is flagged by the caller. */
export function sortedEstimates(rows: readonly AdCloneEstimate[]): AdCloneEstimate[] {
  return [...rows].sort((a, b) => a.usd - b.usd);
}

export function speakerName(key: string): string {
  return ({ H: "Hero", O: "Oxhan", N: "Side character" } as Record<string, string>)[key] ?? key;
}
