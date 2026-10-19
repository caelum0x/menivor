/**
 * Small, pure formatting helpers for the insights dashboard. Kept dependency-free
 * so the stat cards can render server- or client-side without a chart library.
 */

/** Format an integer count with locale grouping (e.g. 1234 -> "1,234"). */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return "0";
  return Math.round(value).toLocaleString("en-US");
}

/** Format a USD amount with two decimals (e.g. 12.5 -> "$12.50"). */
export function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return "$0.00";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
}

/**
 * Format a millisecond duration as a compact, human-readable render time.
 * < 1s -> "820ms"; < 60s -> "8.2s"; otherwise "1m 05s".
 */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;

  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(1)}s`;
  }

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

/** Human-readable label for a job-state key (e.g. "complete" -> "Complete"). */
export function formatStateLabel(state: string): string {
  if (!state) return "Unknown";
  return state.charAt(0).toUpperCase() + state.slice(1).replace(/_/g, " ");
}
