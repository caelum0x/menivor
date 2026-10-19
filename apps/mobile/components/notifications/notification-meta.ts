/**
 * Pure presentation helpers for the notification center: maps a notification
 * `kind` to an icon + accent colour, extracts a deep-link job id from the
 * opaque `data` payload, and formats a compact relative timestamp. Kept
 * dependency-free so it can be unit-tested and reused by the list + badge.
 */

import type { IconName } from "@/components/ui/Icon";
import type { Notification } from "@/lib/types";
import { colors } from "@/components/me/theme";

export interface KindMeta {
  /** Short human label for the event kind. */
  label: string;
  /** Leading Ionicons icon name for the event kind. */
  icon: IconName;
  /** Accent colour for the glyph / unread dot. */
  color: string;
}

const KIND_META: Record<string, KindMeta> = {
  job_complete: { label: "Video ready", icon: "checkmark-circle", color: colors.success },
  job_failed: { label: "Job failed", icon: "alert-circle", color: colors.error },
  low_credits: { label: "Low credits", icon: "wallet", color: "#f5b642" },
  referral_earned: { label: "Referral bonus", icon: "gift", color: colors.accent },
};

const FALLBACK_META: KindMeta = {
  label: "Notification",
  icon: "notifications",
  color: colors.accent,
};

/** Presentation metadata for a notification kind (never throws). */
export function kindMeta(kind: string): KindMeta {
  return KIND_META[kind] ?? FALLBACK_META;
}

/**
 * Pull a deep-linkable job id out of an opaque notification `data` bag, if
 * present. Returns null when there is no usable string `job_id`. Shared by the
 * in-app notification list and the push-notification tap router so both derive
 * the deep-link target the exact same way — a remote push carries its job id in
 * `request.content.data.job_id`, the same shape stored on an in-app row.
 */
export function jobIdFromData(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const raw = (data as Record<string, unknown>).job_id;
  return typeof raw === "string" && raw.length > 0 ? raw : null;
}

/**
 * Pull a deep-linkable job id out of an in-app notification, if present.
 * Returns null when there is no usable string `job_id` (so callers can decide
 * whether tapping should navigate).
 */
export function jobIdFromNotification(notification: Notification): string | null {
  return jobIdFromData(notification.data);
}

/**
 * Format an ISO-8601 timestamp as a compact relative age: "just now", "5m",
 * "3h", "2d", then falls back to a short absolute date. Returns "" when the
 * input is missing or unparseable so the UI can omit the timestamp cleanly.
 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";

  const diffMs = Date.now() - then;
  const seconds = Math.floor(diffMs / 1000);

  if (seconds < 45) return "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;

  return new Date(then).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}
