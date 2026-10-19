/** Pure helpers for the keyword tracker (no React, easy to test). */

import type { HistoryPoint, TrackedKeyword } from "./api";

/** "#2" or "Not in top 50". */
export function formatRank(position: number | null): string {
  return position === null ? "Not in top 50" : `#${position}`;
}

/** "+4" (improved), "-3" (dropped), or "" with no baseline yet. */
export function formatChange(change: number | null): string {
  if (change === null) return "";
  if (change === 0) return "No change";
  return change > 0 ? `+${change}` : `${change}`;
}

/** Tailwind color class for a change value: green = improved, red = dropped. */
export function changeTone(change: number | null): string {
  if (change === null || change === 0) return "text-muted-foreground";
  return change > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive";
}

export interface RankChartGeometry {
  readonly path: string;
  readonly dots: readonly { readonly x: number; readonly y: number }[];
  readonly worst: number;
}

/**
 * SVG path for a rank-over-time sparkline in a `width` x `height` box. Lower
 * rank numbers are better, so the y-axis is inverted (rank 1 draws near the
 * top). A day the app was not in the top 50 breaks the line (gap, not a drop
 * to zero) rather than implying a false rank.
 */
export function rankChartGeometry(
  history: readonly HistoryPoint[],
  width: number,
  height: number,
): RankChartGeometry | null {
  const ranked = history.filter((p) => p.position !== null);
  if (ranked.length < 2 || history.length < 2) return null;
  const worst = Math.max(...ranked.map((p) => p.position as number), 1);
  const pad = 3;
  const step = width / (history.length - 1);
  const y = (position: number) => pad + (height - 2 * pad) * ((position - 1) / Math.max(worst - 1, 1));

  const segments: string[] = [];
  const dots: { x: number; y: number }[] = [];
  let drawing = false;
  history.forEach((point, index) => {
    const x = index * step;
    if (point.position === null) {
      drawing = false;
      return;
    }
    const py = y(point.position);
    dots.push({ x, y: py });
    segments.push(`${drawing ? "L" : "M"}${x.toFixed(1)},${py.toFixed(1)}`);
    drawing = true;
  });
  if (segments.length === 0) return null;
  return { path: segments.join(" "), dots, worst };
}

/** "Oct 9" for an ISO date. */
export function shortDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** Whether `keyword` has ever returned a rank reading. */
export function hasReading(keyword: TrackedKeyword): boolean {
  return keyword.last_checked_at !== null;
}

/** The App Store listing URL for a tracked keyword's app. */
export function appStoreUrl(appId: string): string {
  return `https://apps.apple.com/app/id${encodeURIComponent(appId)}`;
}

/**
 * "72/100" for Apple's Search Popularity index, or "" when it is not
 * available yet (no connected Apple Search Ads account, or Apple has not
 * scored this term). Never shows a fabricated "difficulty" number — Apple's
 * API does not publish one alongside popularity.
 */
export function formatPopularity(popularity: number | null): string {
  return popularity === null ? "" : `${popularity}/100`;
}
