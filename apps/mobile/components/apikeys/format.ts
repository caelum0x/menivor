/**
 * Tiny, dependency-free date helpers for the API keys screen. Hermes has patchy
 * `Intl` support, so timestamps are formatted manually from the parsed `Date`
 * fields rather than via `toLocaleDateString`.
 */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/** Format an ISO-8601 timestamp as "Aug 12, 2026", or "" when absent/invalid. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${MONTHS[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

/** Human label for a key's last-used timestamp (null → "Never used"). */
export function formatLastUsed(iso: string | null | undefined): string {
  const formatted = formatDate(iso);
  return formatted ? `Last used ${formatted}` : "Never used";
}
