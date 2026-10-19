import type { LucideIcon } from "lucide-react";
import { AtSign, Cloud, Facebook, Linkedin, Pin, Twitter } from "lucide-react";
import type { ExtendedPlatform, PlatformState, PostStatus } from "../_lib/publishing-api";

export const PLATFORM_ICONS: Record<ExtendedPlatform, LucideIcon> = {
  facebook: Facebook,
  linkedin: Linkedin,
  x: Twitter,
  threads: AtSign,
  pinterest: Pin,
  bluesky: Cloud,
};

export const PLATFORM_LABELS: Record<ExtendedPlatform, string> = {
  facebook: "Facebook Page",
  linkedin: "LinkedIn",
  x: "X",
  threads: "Threads",
  pinterest: "Pinterest",
  bluesky: "Bluesky",
};

export const STATE_LABELS: Record<PlatformState, string> = {
  not_configured: "Not set up on this server",
  plan_required: "Paid X API plan required",
  not_connected: "Not connected",
  needs_target: "Choose where to post",
  needs_reauth: "Reconnect needed",
  connected: "Connected",
};

export const TARGET_NOUN: Record<string, string> = {
  page: "Page",
  organization: "company page",
  board: "board",
  self: "account",
};

export const POST_STATUS_LABELS: Record<PostStatus, string> = {
  scheduled: "Scheduled",
  publishing: "Posting",
  processing: "Processing on the platform",
  published: "Published",
  failed: "Failed",
  canceled: "Canceled",
  held: "Held for review",
};

export function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
