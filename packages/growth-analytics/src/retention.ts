/** Retention curve + reach tier + drop-off (mirror of `retention.py`). */

import { clamp01, round6 } from "./util.js";

export interface ReachTier {
  tier: "viral" | "boosted" | "minimal";
  multiplier: number;
}

export function normalizeCurve(samples: number[]): number[] {
  if (samples.length === 0) return [];
  const base = samples[0] > 0 ? samples[0] : Math.max(...samples) || 1;
  return samples.map((s) => round6(clamp01(s / base)));
}

export function reachTier(avgRetention: number): ReachTier {
  const r = clamp01(avgRetention);
  if (r >= 0.85) return { tier: "viral", multiplier: 3.0 };
  if (r >= 0.7) return { tier: "boosted", multiplier: 2.2 };
  return { tier: "minimal", multiplier: 1.0 };
}

export interface Dropoff {
  max_drop: number;
  max_drop_at: number;
  first_3s: number;
}

export function dropoff(curve: number[]): Dropoff {
  let maxDrop = 0;
  let at = 0;
  for (let i = 1; i < curve.length; i++) {
    const drop = curve[i - 1] - curve[i];
    if (drop > maxDrop) {
      maxDrop = drop;
      at = i;
    }
  }
  const head = curve.slice(0, 3);
  const first3s = head.length ? round6(head.reduce((a, b) => a + b, 0) / head.length) : 0;
  return { max_drop: round6(maxDrop), max_drop_at: at, first_3s: first3s };
}
