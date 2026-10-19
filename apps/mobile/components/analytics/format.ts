/**
 * Formatting helpers for the creator dashboard. Reuses the shared Me-tab
 * formatters (count / USD / duration) so metrics read identically across the
 * app, and adds a couple of analytics-only helpers. Dependency-free.
 */

export { formatCount, formatDuration, formatUsd } from "@/components/me/format";

/**
 * Format an ISO `YYYY-MM-DD` day as a compact axis label, e.g. "Aug 10".
 * Falls back to the raw string when it can't be parsed.
 */
export function formatDay(iso: string): string {
  if (!iso) return "";
  // Parse as a local date from the Y-M-D parts to avoid UTC off-by-one drift.
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const [, year, month, day] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Percentage of `part` out of `total`, clamped to 0–100. Returns 0 when the
 * total is zero or non-finite (used to size proportional bars safely).
 */
export function toPercent(part: number, total: number): number {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) return 0;
  const pct = (part / total) * 100;
  if (pct < 0) return 0;
  if (pct > 100) return 100;
  return pct;
}

/** Compact count label for breakdown rows, e.g. `1` -> "1 job", `3` -> "3 jobs". */
export function formatJobs(count: number): string {
  const n = Number.isFinite(count) ? Math.round(count) : 0;
  return `${n.toLocaleString("en-US")} ${n === 1 ? "job" : "jobs"}`;
}
