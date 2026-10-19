/** Shared kernel types for `@reelforge/effects-core`. */

export type KernelCategory = "camera" | "vfx";

/** A kernel's output at a normalized time `t`: transform / filter params. */
export type KernelOutput = Record<string, number>;

/** A pure kernel: `(t, params) -> output`. */
export type Kernel = (t: number, params?: Record<string, number>) => KernelOutput;

export interface KernelEntry {
  id: string;
  category: KernelCategory;
  apply: Kernel;
}
