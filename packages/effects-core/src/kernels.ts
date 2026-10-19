/**
 * Camera + VFX preset kernels (mirror of `reelforge_effects_core/kernels.py`).
 * Each returns transform/filter params at normalized time `t`, using only the
 * pure primitives in `keyframe.ts` so output is bit-identical to Python.
 */

import { clamp01, easeInOut, linear, noise1, peak, round9 } from "./keyframe.js";
import type { KernelOutput } from "./types.js";

function r(o: KernelOutput): KernelOutput {
  const out: KernelOutput = {};
  for (const k of Object.keys(o)) out[k] = round9(o[k]);
  return out;
}

// --- Camera ---------------------------------------------------------------- //
export function pushIn(t: number, p: { intensity?: number } = {}): KernelOutput {
  const intensity = p.intensity ?? 0.3;
  return r({ zoom: 1 + intensity * easeInOut(t) });
}

export function kenBurns(
  t: number,
  p: { zoom?: number; pan_x?: number; pan_y?: number } = {},
): KernelOutput {
  const zoom = p.zoom ?? 0.2;
  const panX = p.pan_x ?? 0.1;
  const panY = p.pan_y ?? 0.05;
  return r({ zoom: 1 + zoom * linear(t), x: panX * linear(t), y: panY * linear(t) });
}

export function handheld(t: number, p: { intensity?: number; seed?: number } = {}): KernelOutput {
  const intensity = p.intensity ?? 0.02;
  const seed = p.seed ?? 1;
  const n = Math.round(t * 1000);
  return r({
    dx: intensity * noise1(n, seed),
    dy: intensity * noise1(n, seed + 7),
    rot: intensity * 0.5 * noise1(n, seed + 13),
  });
}

// --- VFX ------------------------------------------------------------------- //
export function rgbSplit(t: number, p: { intensity?: number } = {}): KernelOutput {
  const intensity = p.intensity ?? 4;
  return r({ shift_px: intensity * peak(t) });
}

export function filmGrain(
  t: number,
  p: { intensity?: number; vignette?: number } = {},
): KernelOutput {
  return r({ grain: p.intensity ?? 0.15, vignette: p.vignette ?? 0.3 });
}

export function shake(t: number, p: { intensity?: number; decay?: number } = {}): KernelOutput {
  const intensity = p.intensity ?? 8;
  const decay = p.decay ?? 3;
  let amp = intensity;
  const u = 1 - clamp01(t);
  for (let i = 0; i < decay; i++) amp *= u;
  return r({ amplitude: amp });
}
