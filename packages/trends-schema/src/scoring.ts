/**
 * Pure trend scoring (mirror of `scoring.py`). Same IEEE-754 op sequence +
 * shared `round6` → bit-identical to the Python port (golden fixtures).
 */

export function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

/** Deterministic 6-dp round (half away from zero) — identical in JS/Python. */
export function round6(x: number): number {
  const bias = x >= 0 ? 0.5 : -0.5;
  return Math.trunc(x * 1_000_000 + bias) / 1_000_000;
}

export interface TrendScore {
  saturation: number;
  velocity: number;
  decay: number;
  opportunity: number;
}

export function saturation(series: number[]): number {
  if (series.length === 0) return 0;
  const peak = Math.max(...series);
  if (peak <= 0) return 0;
  return round6(series[series.length - 1] / peak);
}

export function velocity(series: number[], window = 3): number {
  const n = series.length;
  if (n < 2) return 0;
  const k = Math.min(Math.trunc(window), n - 1);
  const peak = Math.max(...series);
  const denom = peak > 0 ? peak : 1;
  const change = series[n - 1] - series[n - 1 - k];
  return round6(change / (k * denom));
}

export function decay(series: number[]): number {
  if (series.length === 0) return 0;
  const peak = Math.max(...series);
  if (peak <= 0) return 0;
  const peakIdx = series.indexOf(peak);
  if (peakIdx < series.length - 1 && series[series.length - 1] < peak) {
    return round6((peak - series[series.length - 1]) / peak);
  }
  return 0;
}

export function opportunity(series: number[]): number {
  const sat = saturation(series);
  const vel = velocity(series);
  const dec = decay(series);
  const rising = clamp01(vel * 10);
  return round6(clamp01(0.5 * rising + 0.4 * (1 - sat) + 0.1 * (1 - dec)));
}

export function score(series: number[]): TrendScore {
  return {
    saturation: saturation(series),
    velocity: velocity(series),
    decay: decay(series),
    opportunity: opportunity(series),
  };
}

export interface SoundFlags {
  licensed?: boolean;
  explicit?: boolean;
}

/** Cross-platform (Meta-compatible) ad-safe rule: licensed + not explicit. */
export function adSafe(sound: SoundFlags): boolean {
  return (sound.licensed ?? true) === true && (sound.explicit ?? false) === false;
}
