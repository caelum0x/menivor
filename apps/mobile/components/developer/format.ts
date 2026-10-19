/**
 * Small presentational helpers for the Developer screen. Pure functions only —
 * formatting event names, delivery status colours, timestamps and counts. No
 * network, no state, no secrets.
 */

import { colors } from "@/components/me/theme";

/** Human-friendly label for a `job.completed`-style event key. */
export function eventLabel(eventType: string): string {
  if (!eventType) return "—";
  return eventType;
}

/**
 * Map a delivery status to a colour token. Unknown / pending is muted, delivered
 * is success, failed is error.
 */
export function statusColor(status: string): string {
  switch ((status || "").toLowerCase()) {
    case "delivered":
      return colors.success;
    case "failed":
      return colors.error;
    default:
      return colors.muted;
  }
}

/** Title-case a delivery status for display (`delivered` -> `Delivered`). */
export function statusLabel(status: string): string {
  const s = (status || "pending").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/**
 * Best-effort short date rendering of an ISO-8601 timestamp. Returns `"—"` for a
 * missing / unparseable value rather than throwing.
 */
export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Best-effort short date + time rendering; `"—"` on a missing / bad value. */
export function shortDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compact integer formatting (e.g. `1,234`), safe for any finite number. */
export function count(n: number): string {
  return Number.isFinite(n) ? Math.max(0, Math.trunc(n)).toLocaleString() : "0";
}

/** Pluralise a noun by count (`1 subscription` / `2 subscriptions`). */
export function plural(n: number, noun: string): string {
  return `${count(n)} ${noun}${n === 1 ? "" : "s"}`;
}
