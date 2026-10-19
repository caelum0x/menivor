import { SOCIAL_PLATFORM_IDS, type SocialPlatform } from "@/lib/types";

/**
 * Display labels for the social platforms the caption generator can tailor copy
 * for. The backend (GET /catalog/social-platforms) is the source of truth; this
 * map is the offline fallback catalog and fills in any name the backend omits.
 */
const PLATFORM_LABELS: Readonly<Record<string, string>> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube_shorts: "YouTube Shorts",
};

/** Local fallback catalog used when GET /catalog/social-platforms is unavailable. */
export const FALLBACK_SOCIAL_PLATFORMS: readonly SocialPlatform[] =
  SOCIAL_PLATFORM_IDS.map((id) => ({ id, name: PLATFORM_LABELS[id] ?? id }));

/** A friendly label for a (possibly forward-compat) platform id. */
export function platformLabel(platform: SocialPlatform): string {
  return platform.name || PLATFORM_LABELS[platform.id] || platform.id;
}
