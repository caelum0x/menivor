/**
 * Formatting helpers for the creator analytics dashboard. Re-exports the shared
 * insights formatters (so cards stay visually consistent) and adds a couple of
 * analytics-specific helpers. Dependency-free — no chart library required.
 */

export {
  formatCount,
  formatUsd,
  formatDuration,
  formatStateLabel,
} from "@/components/insights/format";

/**
 * Format an ISO `YYYY-MM-DD` day bucket as a short "Aug 10" label. Falls back to
 * the raw string when it cannot be parsed, so a malformed bucket still renders.
 */
export function formatDay(date: string): string {
  if (!date) return "";
  // Parse as a UTC calendar date to avoid a local-timezone off-by-one.
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return date;
  const [, year, month, day] = match;
  const parsed = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/**
 * Format a `0..1` fraction as a whole-number percentage (e.g. 0.75 -> "75%").
 * Non-finite input renders as "0%".
 */
export function formatPct(fraction: number): string {
  if (!Number.isFinite(fraction)) return "0%";
  return `${Math.round(fraction * 100)}%`;
}
