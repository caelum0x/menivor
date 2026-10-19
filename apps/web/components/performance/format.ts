/**
 * Small, pure formatting helpers for the Hook Performance dashboard. Kept
 * dependency-free so the panels render without a chart library. Count/USD
 * formatting is reused from the insights dashboard; these cover the
 * performance-specific score + retention values.
 */

/**
 * Format a win score for display. Scores are non-negative and can be fractional,
 * so show up to one decimal but drop a trailing `.0` (e.g. `12` -> "12",
 * `12.34` -> "12.3"). Guards non-finite input to "0".
 */
export function formatScore(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded)
    ? rounded.toLocaleString("en-US")
    : rounded.toLocaleString("en-US", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      });
}

/**
 * Format a retention / watch-through percentage in `[0, 100]` as e.g. "62%".
 * Guards non-finite input to "0%".
 */
export function formatRetention(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0%";
  const clamped = Math.min(100, Math.max(0, value));
  return `${Math.round(clamped)}%`;
}
