/** Hook-strength scoring vs the 70% gate (mirror of `hook.py`). */

import { clamp01, round6 } from "./util.js";

export const GATE = 0.7;

const WEIGHTS: Record<string, number> = {
  motion: 0.35,
  contrast: 0.2,
  text: 0.2,
  audio_onset: 0.25,
};

export interface HookSignals {
  motion?: number;
  contrast?: number;
  text?: number;
  audio_onset?: number;
}

export interface HookResult {
  score: number;
  passes: boolean;
}

export function hookScore(signals: HookSignals): HookResult {
  let total = 0;
  for (const key of Object.keys(WEIGHTS)) {
    total += WEIGHTS[key] * clamp01(Number((signals as Record<string, number>)[key] ?? 0));
  }
  const score = round6(total);
  return { score, passes: score >= GATE };
}
