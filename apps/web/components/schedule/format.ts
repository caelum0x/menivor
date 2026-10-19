/**
 * Formatting helpers for the scheduled-publishes UI. All timestamps stored by
 * the backend are UTC ISO-8601 instants; these render them in the viewer's
 * local timezone.
 */

/** Format an ISO-8601 instant as a readable local date + time, or a fallback. */
export function formatScheduledAt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  return new Date(ms).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** A short relative hint like "in 3 hours" / "2 minutes ago" for a due time. */
export function formatRelative(
  iso: string | null | undefined,
  nowMs = Date.now(),
): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";

  const diffMs = ms - nowMs;
  const abs = Math.abs(diffMs);
  const minutes = Math.round(abs / 60_000);
  const hours = Math.round(abs / 3_600_000);
  const days = Math.round(abs / 86_400_000);

  let value: string;
  if (minutes < 1) value = "less than a minute";
  else if (minutes < 60) value = `${minutes} minute${minutes === 1 ? "" : "s"}`;
  else if (hours < 24) value = `${hours} hour${hours === 1 ? "" : "s"}`;
  else value = `${days} day${days === 1 ? "" : "s"}`;

  return diffMs >= 0 ? `in ${value}` : `${value} ago`;
}
