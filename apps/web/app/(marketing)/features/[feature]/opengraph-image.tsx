import { getFeature, FEATURE_SLUGS } from "@/lib/seo";
import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

/** One card per page so the route is statically known. */
export function generateStaticParams(): Array<{ feature: string }> {
  return FEATURE_SLUGS.map((feature) => ({ feature }));
}

export const alt = "Menivor";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  readonly params: { feature: string };
}

/**
 * Social card for this page. The page sets its own openGraph metadata, which
 * replaces the root card, so without this file the page shared with no image.
 */
export default function Image({ params }: ImageProps) {
  const entry = getFeature(params.feature);
  return renderOgImage({
    eyebrow: "Menivor · Features",
    title: entry?.name ?? "AI video features",
    footer: "menivor.com · make your first reel free",
  });
}
