import type { LucideIcon } from "lucide-react";
import { Instagram, Music2, Youtube } from "lucide-react";
import { PUBLISH_PLATFORMS, type PublishPlatform } from "@/lib/types";

/**
 * Display metadata for the publish platforms handled by
 * app/services/publish.py + upload_post. `PUBLISH_PLATFORMS` (from lib/types) is
 * the source of truth for which platforms exist; this only adds presentation.
 */
export interface PlatformMeta {
  id: PublishPlatform;
  label: string;
  icon: LucideIcon;
}

const META: Record<(typeof PUBLISH_PLATFORMS)[number], Omit<PlatformMeta, "id">> = {
  tiktok: { label: "TikTok", icon: Music2 },
  instagram: { label: "Instagram", icon: Instagram },
  youtube_shorts: { label: "YouTube Shorts", icon: Youtube },
};

/** Ordered platform metadata for rendering the multi-select. */
export const PLATFORM_OPTIONS: readonly PlatformMeta[] = PUBLISH_PLATFORMS.map(
  (id) => ({ id, ...META[id] }),
);

/** Human label for a platform id, falling back to the raw id. */
export function platformLabel(id: PublishPlatform): string {
  return META[id as (typeof PUBLISH_PLATFORMS)[number]]?.label ?? id;
}

/** Whether YouTube Shorts is among the selected platforms. */
export function includesYouTube(platforms: readonly string[]): boolean {
  return platforms.includes("youtube_shorts");
}

// ---------------------------------------------------------------------------
// datetime-local <-> UTC helpers. `<input type="datetime-local">` works in the
// browser's local timezone and has no offset; these convert to/from the UTC
// ISO-8601 instant the backend stores as `scheduled_at`.
// ---------------------------------------------------------------------------

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Format a Date as a local `YYYY-MM-DDTHH:mm` datetime-local value. */
export function toLocalDatetimeValue(date: Date): string {
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/**
 * The earliest selectable datetime-local value: `offsetMs` in the future from
 * now (default one minute), used as the input's `min` so past times can't be
 * picked in supporting browsers.
 */
export function minScheduleValue(offsetMs = 60_000): string {
  return toLocalDatetimeValue(new Date(Date.now() + offsetMs));
}

/**
 * Convert a local `YYYY-MM-DDTHH:mm` datetime-local value to a UTC ISO-8601
 * instant. Returns `null` when the value is empty or unparseable.
 */
export function localDatetimeToUtcISO(value: string): string | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  if (Number.isNaN(ms)) return null;
  return new Date(ms).toISOString();
}

/** Whether a datetime-local value parses to a strictly future instant. */
export function isFutureDatetime(value: string, nowMs = Date.now()): boolean {
  const ms = new Date(value).getTime();
  return !Number.isNaN(ms) && ms > nowMs;
}
