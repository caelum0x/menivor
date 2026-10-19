import { getProvider, PROVIDER_SLUGS } from "@/lib/seo";
import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

/** One card per page so the route is statically known. */
export function generateStaticParams(): Array<{ provider: string }> {
  return PROVIDER_SLUGS.map((provider) => ({ provider }));
}

export const alt = "Menivor";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  readonly params: { provider: string };
}

/**
 * Social card for this page. The page sets its own openGraph metadata, which
 * replaces the root card, so without this file the page shared with no image.
 */
export default function Image({ params }: ImageProps) {
  const entry = getProvider(params.provider);
  return renderOgImage({
    eyebrow: "Menivor · Models",
    title: entry ? `${entry.name} in Menivor` : "AI models in Menivor",
    footer: "menivor.com · make your first reel free",
  });
}
