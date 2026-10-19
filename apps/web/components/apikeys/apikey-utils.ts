import type { ApiKey } from "@/lib/types";

/**
 * Format an ISO-8601 timestamp as a short, locale-aware date (e.g. "Aug 12,
 * 2026"). Returns an empty string for a missing/unparseable value so callers can
 * conditionally render it.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Human label for a key's last-used timestamp: the formatted date, or "Never
 * used" when the key has not yet authenticated a request.
 */
export function formatLastUsed(value: string | null | undefined): string {
  const formatted = formatDate(value);
  return formatted || "Never used";
}

/** Whether a key is currently usable (minted and not revoked). */
export function isActive(key: ApiKey): boolean {
  return !key.revoked;
}
