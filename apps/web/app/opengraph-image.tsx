import {
  renderOgImage,
  OG_SIZE,
  OG_CONTENT_TYPE,
} from "@/lib/seo/og";

/**
 * Default Open Graph card for the whole site. Because it sits at the app root,
 * every route inherits it unless a nested `opengraph-image` overrides it (see
 * the /vs and /tools variants). Fixes the previous state where the layout
 * declared `summary_large_image` with no image.
 */
export const alt = "Menivor — AI UGC video generator";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

export default function Image() {
  return renderOgImage({
    title: "Turn a screen recording into a ready-to-post UGC reel",
  });
}
