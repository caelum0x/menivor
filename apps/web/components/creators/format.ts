/**
 * Small, pure formatting helpers for the creator profile + leaderboard UI.
 * Dependency-free so the cards render without a chart/formatting library.
 */

import type { LeaderboardEntry, LeaderboardMetric } from "@/lib/types";

/** Format a count with locale grouping (e.g. 1234 -> "1,234"; 0/neg -> "0"). */
export function formatCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  return Math.round(value).toLocaleString("en-US");
}

/** Format a mean rating for display (e.g. 4.72 -> "4.7"; 0 -> "New"). */
export function formatRating(avg: number): string {
  if (!Number.isFinite(avg) || avg <= 0) return "New";
  return avg.toFixed(1);
}

/** Format a reputation / win score for display (one decimal; 0/neg -> "0"). */
export function formatScore(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  return value.toFixed(1);
}

/** Human-readable labels for each leaderboard metric (exhaustive over the union). */
const METRIC_LABELS: Record<LeaderboardMetric, string> = {
  reputation: "Reputation",
  followers: "Followers",
  clones: "Clones",
  rating: "Rating",
  published: "Published",
  win_score: "Win score",
};

export function metricLabel(metric: LeaderboardMetric): string {
  return METRIC_LABELS[metric] ?? "Reputation";
}

/** The headline value string to show for the metric a leaderboard is ranked by. */
export function metricValue(
  entry: Readonly<LeaderboardEntry>,
  metric: LeaderboardMetric,
): string {
  switch (metric) {
    case "followers":
      return formatCount(entry.follower_count);
    case "clones":
      return formatCount(entry.total_clones_received);
    case "rating":
      return formatRating(entry.avg_rating);
    case "published":
      return formatCount(entry.published_template_count);
    case "win_score":
      return formatScore(entry.win_score);
    case "reputation":
    default:
      return formatScore(entry.reputation_score);
  }
}

/** The best display name available: real name, else handle, else a safe fallback. */
export function displayName(name: string, handle: string): string {
  const trimmedName = (name || "").trim();
  if (trimmedName) return trimmedName;
  const trimmedHandle = (handle || "").trim();
  if (trimmedHandle) return trimmedHandle;
  return "Anonymous creator";
}

/** The "@handle" label, or null when the creator has not set a handle yet. */
export function handleLabel(handle: string): string | null {
  const trimmed = (handle || "").trim();
  return trimmed ? `@${trimmed}` : null;
}

/** Up-to-two-letter initials for the avatar placeholder (never empty). */
export function initials(name: string, handle: string): string {
  const source = displayName(name, handle);
  const parts = source.split(/\s+/).filter(Boolean);
  const first = parts[0];
  if (!first) return "?";
  const last = parts[parts.length - 1] ?? first;
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  return ((first[0] ?? "") + (last[0] ?? "")).toUpperCase() || "?";
}
