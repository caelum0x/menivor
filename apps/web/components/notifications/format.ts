/**
 * Pure, dependency-light helpers for rendering in-app notifications: a compact
 * relative-time formatter, a per-kind visual descriptor (icon + accent), and
 * the deep-link target for a notification. Kept free of JSX so it can be reused
 * by the bell, the list, and the full-page center.
 */

import {
  Bell,
  CheckCircle2,
  Coins,
  Gift,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { Notification } from "@/lib/types";

/**
 * Format an ISO-8601 timestamp as a compact "time ago" label:
 * < 1m -> "just now"; < 60m -> "5m"; < 24h -> "3h"; < 7d -> "2d"; else a short
 * date. Returns "" for a missing/unparseable timestamp so callers can omit it.
 */
export function formatRelativeTime(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";

  const diffMs = Date.now() - then;
  if (diffMs < 0) return "just now";

  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "just now";
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

/** Visual descriptor for a notification kind (icon + Tailwind accent color). */
export interface NotificationKindMeta {
  readonly icon: LucideIcon;
  /** Tailwind text-color class for the icon. */
  readonly accent: string;
}

const KIND_META: Record<string, NotificationKindMeta> = {
  job_complete: { icon: CheckCircle2, accent: "text-success" },
  job_failed: { icon: XCircle, accent: "text-destructive" },
  low_credits: { icon: Coins, accent: "text-accent" },
  referral_earned: { icon: Gift, accent: "text-primary" },
};

const DEFAULT_KIND_META: NotificationKindMeta = {
  icon: Bell,
  accent: "text-muted-foreground",
};

/** Resolve the icon + accent for a notification kind (generic fallback). */
export function kindMeta(kind: string): NotificationKindMeta {
  return KIND_META[kind] ?? DEFAULT_KIND_META;
}

/** Safely read a string field from a notification's opaque `data` map. */
function dataString(
  data: Record<string, unknown>,
  key: string,
): string | null {
  const value = data[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * The in-app route a notification deep-links to, or `null` when it is purely
 * informational. Prefers the job (when `data.job_id` is present); low-credit
 * nudges point at billing and referral payouts at the referral page.
 */
export function notificationHref(notification: Notification): string | null {
  const jobId = dataString(notification.data, "job_id");
  if (jobId) return `/jobs/${encodeURIComponent(jobId)}`;

  if (notification.kind === "low_credits") return "/billing";
  if (notification.kind === "referral_earned") return "/referral";
  return null;
}
