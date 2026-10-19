/**
 * Small, pure formatting helpers for the marketplace UI. Dependency-free so the
 * template cards render without a chart/formatting library.
 */

/** Format a mean rating for display (e.g. 4.72 -> "4.7"; 0 -> "New"). */
export function formatRating(avg: number): string {
  if (!Number.isFinite(avg) || avg <= 0) return "New";
  return avg.toFixed(1);
}

/** Format a count with locale grouping (e.g. 1234 -> "1,234"). */
export function formatCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  return Math.round(value).toLocaleString("en-US");
}

/** Human-readable label for a language code (e.g. "en" -> "English"). */
const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  tr: "Türkçe",
  es: "Español",
  fr: "Français",
  de: "Deutsch",
  pt: "Português",
  it: "Italiano",
};

export function languageLabel(code: string): string {
  if (!code) return "Any language";
  return LANGUAGE_LABELS[code] ?? code.toUpperCase();
}

/**
 * Format a win-score for display (e.g. 12.345 -> "12.3"). Returns null when the
 * score is absent or non-finite (e.g. non-"proven" sorts or listings with no
 * downstream reels), so callers can omit the badge entirely.
 */
export function formatWinScore(value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value.toFixed(1);
}

/** Human-readable label for a layout id (e.g. "hook_intro" -> "Hook intro"). */
export function layoutLabel(layout: string): string {
  if (!layout) return "Layout";
  return layout.charAt(0).toUpperCase() + layout.slice(1).replace(/_/g, " ");
}
