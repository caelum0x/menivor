import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

export const alt = "Chop, the free Menivor video editor";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

/** /editor sets its own openGraph metadata, which drops the root card. */
export default function Image() {
  return renderOgImage({
    eyebrow: "Menivor · Chop",
    title: "Chop, the free desktop video editor",
    footer: "menivor.com/editor · Mac, Windows and Linux",
  });
}
