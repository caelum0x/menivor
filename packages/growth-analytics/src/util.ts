/** Shared numeric helpers (bit-identical to `_util.py`). */

export function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

export function round6(x: number): number {
  const bias = x >= 0 ? 0.5 : -0.5;
  return Math.trunc(x * 1_000_000 + bias) / 1_000_000;
}
