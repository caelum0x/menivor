/** Display helpers for the social inbox. */

import type { AccessLevel, InboxPost, PostInboxState, ThreadStatus } from "./types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export const STATUS_LABELS: Record<ThreadStatus, string> = {
  needs_reply: "Needs reply",
  replied: "Replied",
  done: "Done",
};

export const STATE_LABELS: Record<PostInboxState, string> = {
  ok: "Syncing",
  not_connected: "Not connected",
  missing_permission: "Needs permission",
  not_offered: "Not available from platform",
  error: "Retrying",
};

export const ACCESS_LABELS: Record<AccessLevel, string> = {
  yes: "Available",
  needs_permission: "Needs permission",
  not_offered: "Not offered by platform",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as ThreadStatus] ?? status;
}

export function stateLabel(state: string): string {
  return STATE_LABELS[state as PostInboxState] ?? state;
}

export function accessLabel(level: string): string {
  return ACCESS_LABELS[level as AccessLevel] ?? level;
}

/** Relative time ("3h ago") for an ISO timestamp; "never" when missing. */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "unknown";
  const diff = Math.max(0, now - at);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(at).toLocaleDateString();
}

/** A count the platform reported, or an em dash when it did not report one. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
}

export function postLabel(post: InboxPost): string {
  if (post.kind === "dm_channel") return `${post.platform_label} direct messages`;
  const title = post.title.trim() || "Untitled post";
  return `${post.platform_label}: ${title}`;
}

export function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return friendlyErrorMessage(err);
  return fallback;
}
