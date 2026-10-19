/**
 * Tiny, dependency-free formatting helpers for the API Usage screen. Hermes has
 * patchy `Intl` support, so the usage period is formatted manually from its
 * `"YYYY-MM"` parts rather than via `toLocaleDateString`.
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

/**
 * Format a `"YYYY-MM"` usage period as "Aug 2026". Returns "" when the input is
 * absent or not a parseable `YYYY-MM` (defensive against a legacy/blank payload).
 */
export function formatPeriod(periodYm: string | null | undefined): string {
  if (!periodYm) return "";
  const match = /^(\d{4})-(\d{2})$/.exec(periodYm.trim());
  if (!match) return "";
  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  if (monthIndex < 0 || monthIndex > 11) return "";
  return `${MONTHS[monthIndex]} ${year}`;
}

/**
 * Fraction of the monthly quota consumed, clamped to [0, 1]. Returns `null` when
 * the key has no positive monthly cap (unlimited), so callers can branch on it.
 */
export function usageRatio(
  used: number,
  monthlyQuota: number | null | undefined,
): number | null {
  if (typeof monthlyQuota !== "number" || !Number.isFinite(monthlyQuota)) {
    return null;
  }
  if (monthlyQuota <= 0) return null;
  const safeUsed = Number.isFinite(used) ? Math.max(0, used) : 0;
  return Math.min(1, safeUsed / monthlyQuota);
}
