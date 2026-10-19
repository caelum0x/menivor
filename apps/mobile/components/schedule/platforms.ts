import {
  SCHEDULE_PLATFORMS,
  YOUTUBE_PRIVACY_STATUSES,
  type SchedulePlatform,
  type YoutubePrivacyStatus,
} from "@/lib/types";

/**
 * Display metadata for the schedulable publish platforms. The `id` is what the
 * backend expects in `SchedulePublishRequest.platforms`; `label` is for the UI.
 * Kept alongside the canonical id list in `lib/types.ts` so the two never drift.
 */
export interface PlatformMeta {
  id: SchedulePlatform;
  label: string;
}

const PLATFORM_LABELS: Record<SchedulePlatform, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube_shorts: "YouTube Shorts",
};

/** The publishable platforms with display labels, in canonical order. */
export const PLATFORM_OPTIONS: readonly PlatformMeta[] = SCHEDULE_PLATFORMS.map(
  (id) => ({ id, label: PLATFORM_LABELS[id] }),
);

/** Human label for a platform id (falls back to the raw id when unknown). */
export function platformLabel(id: string): string {
  return PLATFORM_LABELS[id as SchedulePlatform] ?? id;
}

/** The platform id that carries a YouTube-privacy choice. */
export const YOUTUBE_PLATFORM: SchedulePlatform = "youtube_shorts";

/** Display metadata for the YouTube privacy options. */
export interface PrivacyMeta {
  id: YoutubePrivacyStatus;
  label: string;
}

const PRIVACY_LABELS: Record<YoutubePrivacyStatus, string> = {
  private: "Private",
  unlisted: "Unlisted",
  public: "Public",
};

/** The YouTube privacy options with display labels (default "private" first). */
export const PRIVACY_OPTIONS: readonly PrivacyMeta[] =
  YOUTUBE_PRIVACY_STATUSES.map((id) => ({ id, label: PRIVACY_LABELS[id] }));
