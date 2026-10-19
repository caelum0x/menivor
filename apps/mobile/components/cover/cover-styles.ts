import type { CoverStyle } from "@/lib/types";

/**
 * Local fallback catalog of cover/thumbnail styles, used when
 * GET /catalog/cover-styles is unavailable so the sheet is never empty. The
 * backend remains the source of truth; these ids mirror the server's built-in
 * Pillow-rendered presets. `accent`/`background`/`text` drive the preview
 * swatch on each style chip.
 */
export const FALLBACK_COVER_STYLES: readonly CoverStyle[] = [
  {
    id: "bold_punch",
    name: "Bold Punch",
    description: "Huge white headline on a darkened poster.",
    accent: "#6a5bff",
    background: "#0b0b12",
    text: "#ffffff",
  },
  {
    id: "highlight_bar",
    name: "Highlight Bar",
    description: "Headline sits on a solid accent bar.",
    accent: "#ffd23f",
    background: "#101018",
    text: "#101018",
  },
  {
    id: "gradient_fade",
    name: "Gradient Fade",
    description: "Bottom-anchored text over a vivid gradient.",
    accent: "#ff5c8a",
    background: "#1a0f24",
    text: "#ffffff",
  },
  {
    id: "clean_minimal",
    name: "Clean Minimal",
    description: "Small caption-style headline, lots of breathing room.",
    accent: "#00d0b0",
    background: "#0b0b12",
    text: "#ffffff",
  },
];

/** The default style id selected when the sheet opens. */
export const DEFAULT_COVER_STYLE_ID = FALLBACK_COVER_STYLES[0].id;

/** Fills in a display name for a backend style that omitted one. */
export function withStyleName(style: CoverStyle): CoverStyle {
  return {
    ...style,
    name: style.name || style.id,
    description: style.description || "",
  };
}
