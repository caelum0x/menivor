/** Retention-weighted A/B winner selection (mirror of `ab.py`). */

import { clamp01, round6 } from "./util.js";

export interface Variant {
  id: string;
  completion?: number;
  avg_watch?: number;
}

export interface WinnerResult {
  winner: string | null;
  scores: Record<string, number>;
}

export function selectWinner(variants: Variant[]): WinnerResult {
  if (variants.length === 0) return { winner: null, scores: {} };
  const maxWatch = Math.max(...variants.map((v) => Number(v.avg_watch ?? 0)), 0);
  const denom = maxWatch > 0 ? maxWatch : 1;
  const scores: Record<string, number> = {};
  let bestId: string | null = null;
  let bestScore = -1;
  for (const v of variants) {
    const completion = clamp01(Number(v.completion ?? 0));
    const watchNorm = clamp01(Number(v.avg_watch ?? 0) / denom);
    const s = round6(0.6 * completion + 0.4 * watchNorm);
    scores[v.id] = s;
    if (s > bestScore) {
      bestScore = s;
      bestId = v.id;
    }
  }
  return { winner: bestId, scores };
}
