import { getMakeType, MAKE_TYPE_SLUGS } from "@/lib/seo";
import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

/** Pre-generate a card per content type so the route is statically known. */
export function generateStaticParams(): Array<{ type: string }> {
  return MAKE_TYPE_SLUGS.map((type) => ({ type }));
}

export const alt = "Menivor · what to make";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  readonly params: { type: string };
}

/** Dynamic OG card for `/make/{type}`. */
export default function Image({ params }: ImageProps) {
  const makeType = getMakeType(params.type);
  const title = makeType?.title ?? "Make an AI video";
  return renderOgImage({
    eyebrow: "Menivor · Make",
    title,
    footer: "menivor.com · screen recording → finished reel",
  });
}
