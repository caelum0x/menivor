/**
 * Shared editorial design tokens for the Menivor mobile app.
 *
 * This is the single source of truth for the app's visual language and the
 * React Native port of the web's editorial system (see
 * apps/web/app/globals.css). The identity is a bold editorial monochrome:
 *
 *   - Ink near-black surfaces (paper is the type, ink is the page).
 *   - Warm off-white type on those surfaces.
 *   - Hairline borders, with subtle soft depth (a faint glass edge highlight
 *     and a soft shadow, see surface.ts) so surfaces are calm but not flat.
 *   - Exactly ONE signal color: a calm muted gold (#E6C76A), a softened take on
 *     the product's own `hormozi` caption preset.
 *   - No gradients, no glows, no loud effects.
 *
 * Hex values are converted from the web's HSL channels so the two clients read
 * as one brand. Every later screen imports from here (directly or via the
 * `components/me/theme` re-export) so a palette change happens in one place.
 */

import { Platform } from "react-native";

/**
 * Editorial monochrome palette + the single #E6C76A accent.
 * Frozen so no screen can mutate the shared palette at runtime.
 */
export const palette = {
  /** Page ink — the app background. web: --background 240 5% 4%. */
  ink: "#0a0a0b",
  /** Raised surface (cards, sheets). web: --card 240 4% 6%. */
  surface: "#0f0f10",
  /** Slightly raised surface for nested rows/chips. web: --secondary 240 4% 11%. */
  surfaceAlt: "#1b1b1d",
  /** Muted fill for tracks/insets. web: --muted 240 4% 10%. */
  surfaceMuted: "#191919",
  /** Hairline border. web: --border 240 4% 16%. */
  border: "#27272a",
  /** Input field fill. web: --input 240 4% 14%. */
  input: "#222226",

  /** Warm off-white primary type. web: --foreground 40 12% 92%. */
  paper: "#ece9e1",
  /** Muted secondary type. web: --muted-foreground 40 4% 62%. */
  paperMuted: "#9b978d",
  /** Faint tertiary type (timestamps, hints). */
  paperFaint: "#6f6c65",

  /** The one signal color — calm muted gold (owner rule: no loud colors). */
  accent: "#E6C76A",
  /** Near-black type that sits ON the accent. web: --primary-foreground. */
  accentInk: "#0f0f10",

  /** States. web: --destructive 0 72% 55%, --success 142 71% 45%. */
  danger: "#D0605B",
  success: "#5DB585",
} as const;

/**
 * Semantic color tokens. Screens should reference these by role rather than the
 * raw palette so intent stays legible.
 */
export const colors = {
  bg: palette.ink,
  surface: palette.surface,
  surfaceAlt: palette.surfaceAlt,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  input: palette.input,

  textPrimary: palette.paper,
  textSecondary: palette.paperMuted,
  textFaint: palette.paperFaint,

  /** Signal color for CTAs, active states, and focus rings. */
  accent: palette.accent,
  /** Type/icon color to place on top of an accent fill. */
  onAccent: palette.accentInk,

  success: palette.success,
  danger: palette.danger,
} as const;

/** 4pt spacing scale. */
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

/** Corner radii. Editorial system is tight — 6px default (web --radius). */
export const radius = {
  sm: 4,
  md: 6,
  lg: 10,
  pill: 999,
} as const;

/** Type scale mirroring the web editorial display/body ramp. */
export const typeScale = {
  display: 40,
  title: 28,
  heading: 20,
  subheading: 16,
  body: 15,
  caption: 13,
  micro: 11,
} as const;

/** Font weights used across the app. */
export const weight = {
  regular: "400",
  medium: "500",
  semibold: "600",
  bold: "700",
  black: "800",
} as const;

/**
 * Timecode-style kicker label style, e.g. "01 / RECORD". Monospace, uppercase,
 * wide tracking — the editorial replacement for icon badges. Spread into a
 * `Text` style. Uses the platform monospace face (no bundled font dependency):
 * iOS ships "Courier", Android's generic monospace is "monospace".
 */
export const kicker = {
  fontFamily: Platform.select({ ios: "Courier", default: "monospace" }),
  fontSize: 12,
  fontWeight: weight.medium,
  letterSpacing: 2,
  textTransform: "uppercase",
  color: colors.textSecondary,
} as const;

export type Colors = typeof colors;
export type Palette = typeof palette;
