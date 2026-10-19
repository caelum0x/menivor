import { colors } from "@/components/me/theme";
import type { ScheduledPublish } from "@/lib/types";

import { platformLabel } from "./platforms";

/** A colored status badge (label + color) for a schedule row. */
export interface ScheduleBadge {
  label: string;
  color: string;
}

const STATUS_BADGES: Record<string, ScheduleBadge> = {
  pending: { label: "Scheduled", color: colors.accent },
  publishing: { label: "Publishing…", color: "#f5c451" },
  published: { label: "Published", color: colors.success },
  failed: { label: "Failed", color: colors.error },
  canceled: { label: "Canceled", color: colors.muted },
};

/** Map a schedule status to a display badge (unknown statuses degrade nicely). */
export function statusBadge(status: string): ScheduleBadge {
  return (
    STATUS_BADGES[status] ?? { label: status || "Unknown", color: colors.muted }
  );
}

/** True only for a still-cancelable schedule. */
export function isPending(row: ScheduledPublish): boolean {
  return row.status === "pending";
}

/** Comma-joined human labels for a schedule's target platforms. */
export function platformSummary(row: ScheduledPublish): string {
  const list = row.platforms ?? [];
  if (list.length === 0) return "No platforms";
  return list.map(platformLabel).join(", ");
}

/**
 * Format an ISO-8601 UTC `scheduled_at` into a friendly local-time label. Falls
 * back to the raw value when it is missing or unparseable so the UI never blanks.
 */
export function formatScheduledAt(iso: string | null): string {
  if (!iso) return "Time not set";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  try {
    return date.toLocaleString(undefined, {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
