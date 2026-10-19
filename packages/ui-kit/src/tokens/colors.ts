/**
 * Named color tokens — the single ReelForge palette. Matches the existing mobile
 * theme (`apps/mobile/components/me/theme.ts`) so web, mobile, Electron, and the
 * Rust/GPUI desktop (via `tokens.json`) all share one palette.
 */

export const colors = {
  // Surfaces
  bg: "#0b0b12",
  surface: "#15151f",
  surfaceAlt: "#1b1b28",
  border: "#2a2a3a",
  // Brand
  primary: "#6a5bff",
  accent: "#8b7bff",
  // Text
  textPrimary: "#ffffff",
  textSecondary: "#c9c9d6",
  muted: "#6b6b7b",
  // Status
  success: "#4ade80",
  warning: "#fbbf24",
  error: "#ff6b6b",
} as const;

/** Per-platform brand colors for PlatformIcon / badges. */
export const platformColors = {
  tiktok: "#25f4ee",
  instagram: "#e1306c",
  youtube: "#ff0000",
  x: "#000000",
} as const;

export type ColorToken = keyof typeof colors;
export type PlatformColor = keyof typeof platformColors;
