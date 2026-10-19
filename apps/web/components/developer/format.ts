/**
 * Small, pure formatting helpers for the developer portal. Dependency-free so
 * the webhook + integration cards render without any chart/date library.
 */

import type { BadgeVariant } from "@/components/ui/badge";
import type { WebhookDelivery } from "@/lib/types";

/** Render an ISO-8601 timestamp as a local, human-friendly string (`—` when absent). */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

/** Compact integer formatting for counts (e.g. `1,234`). */
export function formatCount(value: number | null | undefined): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return Math.max(0, Math.round(n)).toLocaleString("en-US");
}

/**
 * Map a delivery `status` to a {@link Badge} variant: `delivered` reads as
 * success, `failed` as destructive, and anything else (e.g. `pending`) as a calm
 * secondary.
 */
export function deliveryStatusVariant(
  status: WebhookDelivery["status"],
): BadgeVariant {
  if (status === "delivered") return "success";
  if (status === "failed" || status === "dead") return "destructive";
  return "secondary";
}

/** Human label for a delivery status (capitalised; falls back to the raw value). */
export function deliveryStatusLabel(
  status: WebhookDelivery["status"],
): string {
  const s = String(status || "").trim();
  if (!s) return "Pending";
  // Every retry was spent; say so plainly instead of the internal word.
  if (s === "dead") return "Gave up after retries";
  return s.charAt(0).toUpperCase() + s.slice(1);
}
