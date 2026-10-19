import { getPlatform, PLATFORM_SLUGS } from "@/lib/seo";
import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

/** Pre-generate a card per platform so the route is statically known. */
export function generateStaticParams(): Array<{ platform: string }> {
  return PLATFORM_SLUGS.map((platform) => ({ platform }));
}

export const alt = "Menivor AI video by platform";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  readonly params: { platform: string };
}

/** Dynamic OG card for `/for/{platform}`. */
export default function Image({ params }: ImageProps) {
  const platform = getPlatform(params.platform);
  const title = platform ? `AI video for ${platform.name}` : "AI video by platform";
  return renderOgImage({
    eyebrow: "Menivor · By platform",
    title,
    footer: "menivor.com · native 9:16, captioned, ready to post",
  });
}
