/** Display helpers for the winner loop screens (pure, unit-tested). */

import type { LoopDetail, LoopMode, LoopStatus, RemakeResult } from "./types";

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

/** Timeline event kinds -> label (unknown kinds show their raw id). */
export const TIMELINE_LABELS: Record<string, string> = {
  configured: "Loop updated",
  scheduled: "Post scheduled",
  published: "Posted",
  failed: "Post failed",
  held: "Held for review",
  measured: "Early read",
  extended: "Not decisive yet",
  inconclusive: "No usable data",
  winner: "Winner picked",
  remake_started: "Remake started",
  remake_failed: "Remake problem",
  cap_reached: "Spend cap reached",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as LoopStatus] ?? (status || "Unknown");
}

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

export function timelineLabel(kind: string): string {
  return TIMELINE_LABELS[kind] ?? kind;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  return Math.round(value).toLocaleString("en-US");
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

/**
 * Completion / rewatch rates are null when no platform reported them. That is
 * "not measured", never 0%: a zero would claim nobody finished or replayed.
 */
export function formatMeasuredPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "not measured";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "-";
  const t = Date.parse(value);
  if (Number.isNaN(t)) return "-";
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

/** Whether "Check now" / next-check info applies (the loop is collecting data). */
export function isCollecting(status: LoopStatus): boolean {
  return status === "live" || status === "measuring";
}

/** What the remake button does right now, or null when it should not show. */
export function remakeAction(
  detail: Pick<LoopDetail, "winner_job_id" | "remake_batch_id" | "conclusive" | "remake_cost_credits">,
  confirmingLowConfidence: boolean,
): { label: string; needsConfirm: boolean } | null {
  if (!detail.winner_job_id || detail.remake_batch_id) return null;
  const cost = `${detail.remake_cost_credits} credits`;
  if (!detail.conclusive && !confirmingLowConfidence) {
    return { label: `Remake winner (${cost})`, needsConfirm: true };
  }
  return {
    label: confirmingLowConfidence ? `Confirm remake (${cost})` : `Remake winner (${cost})`,
    needsConfirm: false,
  };
}

/** Result copy after a remake starts. */
export function remakeNotice(result: Pick<RemakeResult, "job_ids" | "enqueue_failures" | "credits" | "replayed">): string {
  if (result.replayed) return "This winner was already remade. Opening the next round shows its variants.";
  const failed = result.enqueue_failures.length;
  if (failed > 0) {
    return `${result.job_ids.length - failed} of ${result.job_ids.length} new variants started; the rest were refunded.`;
  }
  return `${result.job_ids.length} new variants are rendering (${result.credits} credits).`;
}

export interface LoopSettingsDraft {
  readonly cap: string;
  readonly minViews: string;
}

/** Validate the spend cap (0..1000) and min views (0..100000) inputs. */
export function parseLoopSettings(draft: LoopSettingsDraft): {
  cap: number | null;
  minViews: number | null;
} {
  const cap = /^\d{1,4}$/.test(draft.cap.trim()) ? Number.parseInt(draft.cap, 10) : Number.NaN;
  const minViews = /^\d{1,6}$/.test(draft.minViews.trim())
    ? Number.parseInt(draft.minViews, 10)
    : Number.NaN;
  return {
    cap: Number.isFinite(cap) && cap >= 0 && cap <= 1000 ? cap : null,
    minViews: Number.isFinite(minViews) && minViews >= 0 && minViews <= 100_000 ? minViews : null,
  };
}

export function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
