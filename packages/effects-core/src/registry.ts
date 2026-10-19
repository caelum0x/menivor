/** Kernel registry (mirror of `reelforge_effects_core/registry.py`). */

import {
  filmGrain,
  handheld,
  kenBurns,
  pushIn,
  rgbSplit,
  shake,
} from "./kernels.js";
import type { Kernel, KernelCategory, KernelEntry, KernelOutput } from "./types.js";

const ENTRIES: KernelEntry[] = [
  { id: "push-in", category: "camera", apply: pushIn },
  { id: "ken-burns", category: "camera", apply: kenBurns },
  { id: "handheld", category: "camera", apply: handheld },
  { id: "rgb-split", category: "vfx", apply: rgbSplit },
  { id: "film-grain", category: "vfx", apply: filmGrain },
  { id: "shake", category: "vfx", apply: shake },
];

const BY_ID = new Map<string, KernelEntry>(ENTRIES.map((e) => [e.id, e]));

export function getKernel(id: string): Kernel | undefined {
  return BY_ID.get(id)?.apply;
}

export function categoryOf(id: string): KernelCategory | undefined {
  return BY_ID.get(id)?.category;
}

export function listKernels(category?: KernelCategory): string[] {
  return ENTRIES.filter((e) => category === undefined || e.category === category)
    .map((e) => e.id)
    .sort();
}

export function apply(id: string, t: number, params?: Record<string, number>): KernelOutput {
  const fn = getKernel(id);
  if (!fn) throw new Error(`unknown kernel ${id}`);
  return fn(t, params);
}
