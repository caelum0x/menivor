/**
 * `@reelforge/effects-core` — shared camera + VFX preset kernels.
 *
 * Pure, deterministic kernel math kept bit-identical with the Python port
 * (`reelforge_effects_core`) so the effect picker / live preview and the render
 * executor apply the same numbers. Kernel output feeds `render-core` transforms.
 */

export * from "./types.js";
export * from "./keyframe.js";
export * from "./kernels.js";
export * from "./ffexpr.js";
export {
  getKernel,
  categoryOf,
  listKernels,
  apply,
} from "./registry.js";
