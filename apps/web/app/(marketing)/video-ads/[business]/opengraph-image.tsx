import { getVertical, VERTICAL_SLUGS } from "@/lib/seo";
import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

/** One card per page so the route is statically known. */
export function generateStaticParams(): Array<{ business: string }> {
  return VERTICAL_SLUGS.map((business) => ({ business }));
}

export const alt = "Menivor";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  readonly params: { business: string };
}

/**
 * Social card for this page. The page sets its own openGraph metadata, which
 * replaces the root card, so without this file the page shared with no image.
 */
export default function Image({ params }: ImageProps) {
  const entry = getVertical(params.business);
  return renderOgImage({
    eyebrow: "Menivor · Video ads",
    title: entry ? `Video ads for ${entry.plural}` : "Video ads for local businesses",
    footer: "menivor.com · make your first reel free",
  });
}
