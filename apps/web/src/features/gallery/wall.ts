import type { ShowcaseGroup, ShowcaseMedia } from "@/lib/styles/showcase";
import { galleryWall, type GalleryItem } from "./api";

/** Most gallery items one landing wall shows (owner-approved only). */
export const GALLERY_WALL_MAX = 6;

/** A gallery item as a moving landing tile (the wall's `gallery` data source). */
export function toShowcaseMedia(item: GalleryItem, group: ShowcaseGroup): ShowcaseMedia {
  return {
    key: `gallery-${item.id}`,
    niche: item.title,
    styleId: null,
    hook: item.title,
    group,
    footage: "page",
    label: item.preset_name || "Gallery",
    mp4: item.preview_url,
    poster: item.poster_url,
    full: item.preview_url,
    fallbackMp4: item.preview_url,
    fallbackPoster: item.poster_url,
  };
}

/** The landing never waits longer than this for the gallery (then it shows our own reels only). */
export const GALLERY_WALL_TIMEOUT_MS = 1500;

/** Up to six owner-approved gallery items for one wall; an outage or a slow API yields none. */
export async function galleryWallMedia(
  group: ShowcaseGroup,
  timeoutMs: number = GALLERY_WALL_TIMEOUT_MS,
): Promise<readonly ShowcaseMedia[]> {
  try {
    const signal = typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(timeoutMs) : undefined;
    const items = await galleryWall({ signal });
    return items.slice(0, GALLERY_WALL_MAX).map((item) => toShowcaseMedia(item, group));
  } catch {
    return [];
  }
}
