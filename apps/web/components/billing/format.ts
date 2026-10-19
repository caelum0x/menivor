/**
 * Small, pure formatting helpers for the workspace billing surfaces. Money is
 * always an INTEGER minor unit (cents) coming off the API — never a float — so
 * every currency string is derived by dividing by 100 exactly once, here. Kept
 * dependency-free so cards render without pulling extra libraries.
 */

import type {
  BadgeVariant,
} from "@/components/ui/badge";
import type {
  Invoice,
  MetricOverage,
  SubscriptionInterval,
} from "@/lib/types";

/**
 * Render an integer cents amount in `currency` (ISO-4217, default USD). Guards
 * against non-finite input so a malformed amount still renders rather than
 * throwing. The division by 100 is the single cents→major-unit boundary.
 */
export function formatCents(
  cents: number | null | undefined,
  currency = "USD",
): string {
  const safe = typeof cents === "number" && Number.isFinite(cents) ? cents : 0;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: (currency || "USD").toUpperCase(),
    }).format(safe / 100);
  } catch {
    // Unknown currency code — fall back to a plain USD-style string.
    return `$${(safe / 100).toFixed(2)}`;
  }
}

/** Suffix for a billing cadence, e.g. `"/mo"` or `"/yr"`. */
export function intervalSuffix(interval: SubscriptionInterval): string {
  return interval === "year" ? "/yr" : "/mo";
}

/** Long label for a cadence, e.g. `"per year"`. */
export function intervalLabel(interval: SubscriptionInterval): string {
  return interval === "year" ? "per year" : "per month";
}

/** Whole-integer count with thousands separators. */
export function formatCount(value: number | null | undefined): string {
  const safe = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return Math.round(safe).toLocaleString("en-US");
}

/**
 * Friendly label for a metric key: known metrics get curated copy, everything
 * else is title-cased from `snake_case` so a new backend metric still reads
 * cleanly without a code change.
 */
const METRIC_LABELS: Record<string, string> = {
  renders: "Reels rendered",
  reels: "Reels rendered",
  credits: "Credits used",
  monthly_credits: "Credits used",
  api_calls: "API calls",
  api_requests: "API calls",
  seats: "Seats",
  storage_gb: "Storage (GB)",
  minutes: "Render minutes",
};

export function metricLabel(metric: string): string {
  const known = METRIC_LABELS[metric];
  if (known) return known;
  return (metric || "Usage")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Whether a per-metric limit is a finite cap (vs unbounded / unlimited). */
export function isBounded(limit: number | null | undefined): limit is number {
  return typeof limit === "number" && Number.isFinite(limit) && limit >= 0;
}

/**
 * Fraction of a metric's allotment consumed, clamped to `[0, 100]`. Unbounded
 * metrics report 0 (no cap to fill); a zero limit that has been used reads as
 * fully consumed (100) so it still surfaces visually.
 */
export function metricPercent(overage: Readonly<MetricOverage>): number {
  if (!isBounded(overage.limit)) return 0;
  const used = Math.max(0, overage.used);
  if (overage.limit <= 0) return used > 0 ? 100 : 0;
  return Math.min(100, Math.max(0, (used / overage.limit) * 100));
}

/** Badge variant for a usage meter — warns as the allotment nears/exceeds. */
export function usageBadgeVariant(
  overage: Readonly<MetricOverage>,
): BadgeVariant {
  if (overage.overage > 0) return "destructive";
  const percent = metricPercent(overage);
  if (percent >= 90) return "destructive";
  if (percent >= 70) return "default";
  return "success";
}

/** Badge variant for a subscription lifecycle status. */
export function subscriptionStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "active":
    case "trialing":
      return "success";
    case "past_due":
      return "destructive";
    case "canceled":
      return "secondary";
    default:
      return "outline";
  }
}

/** Badge variant for an invoice status. */
export function invoiceStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "paid":
      return "success";
    case "open":
      return "default";
    case "void":
      return "destructive";
    case "draft":
    default:
      return "secondary";
  }
}

/** Human label for a subscription status (title-cased, spaces for `_`). */
export function statusLabel(status: string): string {
  return (status || "unknown")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Format an ISO timestamp as a short date (e.g. `"Aug 13, 2026"`). Returns a
 * dash for missing/invalid input so a row never renders `Invalid Date`.
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Render a `'YYYY-MM'` billing period as a friendly month label
 * (e.g. `"2026-08"` → `"August 2026"`). Falls back to the raw value when it is
 * not a parseable `YYYY-MM` string.
 */
export function formatPeriod(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period ?? "");
  if (!match) return period || "This month";
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) return period;
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** The current billing month as `'YYYY-MM'` (UTC), for the usage default. */
export function currentPeriod(): string {
  const now = new Date();
  const year = now.getUTCFullYear();
  const month = `${now.getUTCMonth() + 1}`.padStart(2, "0");
  return `${year}-${month}`;
}

/** Format a single entitlement value for display (numbers, booleans, strings). */
export function formatEntitlementValue(
  value: number | boolean | string,
): string {
  if (typeof value === "boolean") return value ? "Included" : "Not included";
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value < 0) return "Unlimited";
    return formatCount(value);
  }
  return String(value);
}

/**
 * Escape one CSV field: wrap in quotes and double any embedded quotes so a
 * description containing commas/quotes/newlines round-trips safely.
 */
function csvField(value: string | number): string {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

/**
 * Build a self-contained CSV receipt for one invoice from data the tenant
 * already holds — no extra endpoint, and it can never leak another tenant's
 * rows because it only serializes the invoice passed in. Amounts stay integer
 * cents in the raw column and are also rendered in the invoice `currency`.
 */
export function invoiceToCsv(invoice: Readonly<Invoice>): string {
  const header = [
    "Line",
    "Description",
    "Quantity",
    "Amount (cents)",
    "Amount",
  ];
  const lines = invoice.line_items.map((item, index) =>
    [
      index + 1,
      item.description,
      item.quantity,
      item.amount_cents,
      formatCents(item.amount_cents, invoice.currency),
    ]
      .map(csvField)
      .join(","),
  );
  const totalRow = [
    "",
    "Total",
    "",
    invoice.amount_cents,
    formatCents(invoice.amount_cents, invoice.currency),
  ]
    .map(csvField)
    .join(",");
  return [header.map(csvField).join(","), ...lines, totalRow].join("\r\n");
}
