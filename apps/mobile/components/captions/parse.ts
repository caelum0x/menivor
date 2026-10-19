/**
 * Pure input helpers for the Caption Studio. Boundary validation for the free-
 * text numeric fields (loop / beat tools) and the script→word-timings probe fed
 * to the Hormozi grouping endpoint. Kept side-effect free so they are trivially
 * unit-testable and reusable across screens.
 */

import type { WordIn } from "@/lib/captions";

/**
 * Parse a comma / space / newline separated list of finite numbers. Invalid
 * tokens are dropped. Returns the parsed values plus a count of skipped tokens
 * so the UI can surface a soft warning without failing the whole field.
 */
export function parseNumberList(raw: string): {
  values: number[];
  skipped: number;
} {
  const tokens = String(raw ?? "")
    .split(/[\s,]+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  const values: number[] = [];
  let skipped = 0;
  for (const token of tokens) {
    const n = Number(token);
    if (Number.isFinite(n)) values.push(n);
    else skipped += 1;
  }
  return { values, skipped };
}

/**
 * Turn a script line into evenly word-timed cues over `durationS`. This stands
 * in for the render pipeline's whisper word timings so the Hormozi grouping
 * preview reflects real cue boundaries. Punctuation is preserved on the token;
 * empty tokens are dropped.
 */
export function tokenizeScript(script: string, durationS: number): WordIn[] {
  const tokens = String(script ?? "")
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  if (tokens.length === 0) return [];
  const total = durationS > 0 ? durationS : tokens.length * 0.4;
  const per = total / tokens.length;
  return tokens.map((text, i) => ({
    text,
    start: Number((i * per).toFixed(3)),
    end: Number(((i + 1) * per).toFixed(3)),
  }));
}

/** Count non-empty whitespace-delimited tokens in a script. */
export function wordCount(script: string): number {
  return String(script ?? "")
    .split(/\s+/)
    .filter((t) => t.trim().length > 0).length;
}

/** Clamp a number into [0, 1] rounded to 2dp (matches the hook probe range). */
export function clamp01(v: number): number {
  return Math.max(0, Math.min(1, Math.round(v * 100) / 100));
}
