import type { WatermarkPosition } from "@/lib/types";

/**
 * Shared constants + helpers for the Brand Watermark surface. Framework-free so
 * the editor, position picker, and preview can all import them without React.
 */

/** Only transparent PNG logos are accepted (the compose overlay expects RGBA). */
export const LOGO_ACCEPT = "image/png";

/** Max accepted logo size (bytes). Logos are small, simple marks. */
export const MAX_LOGO_BYTES = 5 * 1024 * 1024; // 5 MB

/**
 * Logo width as a fraction of the frame width in the preview. Matches the
 * backend `_WATERMARK_SCALE` (0.16) so the on-screen placement mirrors the
 * rendered reel.
 */
export const PREVIEW_LOGO_WIDTH_FRACTION = 0.16;

/** Human-readable labels for each watermark corner. */
export const POSITION_LABELS: Record<WatermarkPosition, string> = {
  top_left: "Top left",
  top_right: "Top right",
  bottom_left: "Bottom left",
  bottom_right: "Bottom right",
};

/**
 * Tailwind absolute-position classes that pin the logo to each corner inside a
 * `relative` preview frame, with a small inset margin (~4%).
 */
export const POSITION_CLASSES: Record<WatermarkPosition, string> = {
  top_left: "top-[4%] left-[4%]",
  top_right: "top-[4%] right-[4%]",
  bottom_left: "bottom-[4%] left-[4%]",
  bottom_right: "bottom-[4%] right-[4%]",
};

/** Clamp an opacity into the `[0, 1]` range the backend accepts. */
export function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/** Format an opacity (0..1) as a whole-number percentage label. */
export function opacityPercentLabel(value: number): string {
  return `${Math.round(clampOpacity(value) * 100)}%`;
}
