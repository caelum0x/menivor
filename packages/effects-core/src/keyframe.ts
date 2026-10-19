/**
 * Pure easing + deterministic-noise primitives shared by every kernel.
 *
 * Pure polynomial / 32-bit-integer math only (no `Math.sin`/`Math.pow` float
 * transcendentals) so this is bit-identical to the Python port
 * (`reelforge_effects_core/easing.py`) — the reason effects-core exists.
 */

export function clamp01(t: number): number {
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

export function linear(t: number): number {
  return clamp01(t);
}

/** Quadratic ease-in-out on [0,1]. */
export function easeInOut(t: number): number {
  t = clamp01(t);
  if (t < 0.5) return 2 * t * t;
  const u = 1 - t;
  return 1 - 2 * u * u;
}

/** Parabola peaking at 1.0 at t=0.5, 0.0 at the ends. */
export function peak(t: number): number {
  t = clamp01(t);
  return 4 * t * (1 - t);
}

const HASH = 2654435761; // Knuth multiplicative hash
const MOD = 4294967296; // 2**32

/** Deterministic pseudo-noise in [-1, 1] (values stay < 2**53 → matches Python). */
export function noise1(n: number, seed = 0): number {
  const h = (((n | 0) + (seed | 0)) * HASH) % MOD;
  return (h / MOD) * 2 - 1;
}

/** Round to 9 dp — matches the Python kernels' output rounding (golden parity). */
export function round9(v: number): number {
  return Math.round(v * 1e9) / 1e9;
}
