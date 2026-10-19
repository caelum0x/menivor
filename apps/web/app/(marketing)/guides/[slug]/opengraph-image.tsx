import { getGuide, GUIDE_SLUGS } from "@/lib/seo";
import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

/** One card per page so the route is statically known. */
export function generateStaticParams(): Array<{ slug: string }> {
  return GUIDE_SLUGS.map((slug) => ({ slug }));
}

export const alt = "Menivor";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  readonly params: { slug: string };
}

/**
 * Social card for this page. The page sets its own openGraph metadata, which
 * replaces the root card, so without this file the page shared with no image.
 */
export default function Image({ params }: ImageProps) {
  const entry = getGuide(params.slug);
  return renderOgImage({
    eyebrow: "Menivor · Guides",
    title: entry?.title ?? "AI video guides",
    footer: "menivor.com · make your first reel free",
  });
}
