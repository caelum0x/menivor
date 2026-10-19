/** Display helpers for the winner loop UI. */

import type { LoopMode, LoopStatus } from "./types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export const STATUS_LABELS: Record<LoopStatus, string> = {
  not_configured: "Loop off",
  awaiting_render: "Rendering variants",
  publishing: "Publishing",
  waiting_for_posts: "Waiting for posts",
  live: "Live, collecting data",
  measuring: "Measuring",
  winner_ready: "Winner picked",
  remaking: "Remaking",
  remade: "Remade",
  cap_reached: "Spend cap reached",
  inconclusive: "No usable data",
};

export const MODE_LABELS: Record<LoopMode, string> = {
  off: "Off",
  manual: "Manual remake",
  auto: "Auto remake",
};

export const PLATFORM_LABELS: Record<string, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube Shorts",
  youtube_shorts: "YouTube Shorts",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as LoopStatus] ?? (status || "Unknown");
}

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(undefined, { notation: value >= 10000 ? "compact" : "standard" }).format(value);
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
  const t = Date.parse(value);
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "in 5h" / "3h ago" relative phrase for a timestamp. */
export function relativeTime(value: string | null | undefined, now = Date.now()): string {
  if (!value) return "";
  const t = Date.parse(value);
  if (Number.isNaN(t)) return "";
  const diffH = Math.round((t - now) / 3_600_000);
  if (Math.abs(diffH) < 1) return diffH >= 0 ? "within the hour" : "just now";
  if (Math.abs(diffH) < 48) return diffH > 0 ? `in ${diffH}h` : `${-diffH}h ago`;
  const days = Math.round(diffH / 24);
  return days > 0 ? `in ${days}d` : `${-days}d ago`;
}

export function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return friendlyErrorMessage(err);
  return fallback;
}
