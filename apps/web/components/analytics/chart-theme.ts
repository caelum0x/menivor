/**
 * Shared chart palette + axis defaults for the analytics dashboard. Colours are
 * literal HSL strings resolved from the same design tokens used across the app
 * (see `app/globals.css`) so the Recharts SVG matches the rest of the UI without
 * needing runtime CSS-variable resolution (which SSR/hydration can't see).
 */

export const CHART_COLORS = {
  primary: "hsl(262 83% 62%)",
  accent: "hsl(191 91% 55%)",
  success: "hsl(142 71% 45%)",
  destructive: "hsl(0 72% 58%)",
  muted: "hsl(240 5% 65%)",
  grid: "hsl(240 5% 18%)",
} as const;

/** A rotating categorical palette for breakdown charts (layout/language/etc.). */
export const CATEGORICAL_COLORS: readonly string[] = [
  CHART_COLORS.primary,
  CHART_COLORS.accent,
  CHART_COLORS.success,
  "hsl(320 70% 60%)",
  "hsl(40 90% 58%)",
  "hsl(210 80% 60%)",
  "hsl(160 60% 50%)",
] as const;

/** Common cartesian-axis tick styling shared by the time-series charts. */
export const AXIS_TICK = {
  fill: CHART_COLORS.muted,
  fontSize: 11,
} as const;

/** Pick a stable categorical colour for the `index`-th series/slice. */
export function categoricalColor(index: number): string {
  const safeIndex =
    ((Math.trunc(index) % CATEGORICAL_COLORS.length) + CATEGORICAL_COLORS.length) %
    CATEGORICAL_COLORS.length;
  return CATEGORICAL_COLORS[safeIndex] ?? CHART_COLORS.primary;
}
