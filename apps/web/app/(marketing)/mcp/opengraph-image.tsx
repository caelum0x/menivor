import { renderOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/seo/og";

export const alt = "Menivor · MCP";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

/** Hub card: the page sets its own openGraph metadata, which drops the root card. */
export default function Image() {
  return renderOgImage({
    eyebrow: "Menivor · MCP",
    title: "Make reels from Claude, Cursor and other agents",
    footer: "menivor.com · make your first reel free",
  });
}
