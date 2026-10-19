/**
 * Small, pure formatting helpers for the API-key usage dashboard. Kept
 * dependency-free so the usage cards can render without a chart library. Count
 * formatting is reused from the insights dashboard to keep number styling
 * consistent across the app.
 */

import type { ApiKeyUsage } from "@/lib/types";

export { formatCount } from "@/components/insights/format";

/**
 * Render a `'YYYY-MM'` billing period as a friendly month label
 * (e.g. `"2026-08"` -> `"August 2026"`). Falls back to the raw value when it is
 * not a parseable `YYYY-MM` string so an unexpected shape still renders.
 */
export function formatPeriod(periodYm: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(periodYm ?? "");
  if (!match) return periodYm || "This month";
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) return periodYm;
  const date = new Date(Date.UTC(year, month - 1, 1));
  return date.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/**
 * Describe a per-minute rate limit for display. `null`/`undefined` means the key
 * inherits the plan default; a finite positive number is shown as `"N / min"`.
 */
export function formatRateLimit(perMin: number | null | undefined): string {
  if (typeof perMin !== "number" || !Number.isFinite(perMin) || perMin <= 0) {
    return "Default";
  }
  const count = Math.round(perMin).toLocaleString("en-US");
  return `${count} / min`;
}

/** Whether a key has a finite monthly quota (as opposed to being unlimited). */
export function hasMonthlyQuota(quota: number | null | undefined): quota is number {
  return typeof quota === "number" && Number.isFinite(quota) && quota > 0;
}

/**
 * Fraction of the monthly quota consumed, clamped to `[0, 100]`. Returns 0 for
 * unlimited keys (no quota to fill).
 */
export function usagePercent(usage: Readonly<ApiKeyUsage>): number {
  if (!hasMonthlyQuota(usage.monthly_quota)) return 0;
  const used = Math.max(0, Number.isFinite(usage.used) ? usage.used : 0);
  return Math.min(100, Math.max(0, (used / usage.monthly_quota) * 100));
}

/**
 * Requests remaining this month, floored at 0. Prefers the server-supplied
 * `remaining`; otherwise derives it from `monthly_quota - used`. Returns `null`
 * for unlimited keys.
 */
export function remainingRequests(
  usage: Readonly<ApiKeyUsage>,
): number | null {
  if (!hasMonthlyQuota(usage.monthly_quota)) return null;
  if (typeof usage.remaining === "number" && Number.isFinite(usage.remaining)) {
    return Math.max(0, usage.remaining);
  }
  const used = Math.max(0, Number.isFinite(usage.used) ? usage.used : 0);
  return Math.max(0, usage.monthly_quota - used);
}

/**
 * Map a quota-fill percentage to a {@link Badge} variant so a nearly-exhausted
 * quota reads as a warning (destructive at >= 90%, muted default 70-90%, and a
 * calm success below 70%).
 */
export function quotaBadgeVariant(
  percent: number,
): "success" | "default" | "destructive" {
  if (percent >= 90) return "destructive";
  if (percent >= 70) return "default";
  return "success";
}
