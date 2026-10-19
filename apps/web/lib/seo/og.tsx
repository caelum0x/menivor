/**
 * Shared Open Graph image renderer for the file-based `opengraph-image` routes.
 *
 * Kept out of the `@/lib/seo` barrel on purpose: it imports `next/og`
 * (ImageResponse), which should only be pulled into the image-generation routes,
 * not into every marketing page bundle. Import it directly from
 * `@/lib/seo/og` in `opengraph-image.tsx` files.
 *
 * Colours mirror the brand tokens in `globals.css` (near-black background, gold
 * primary, cream foreground) so social cards match the site. No custom fonts are
 * loaded — `next/og` supplies a default — which keeps the build dependency-free
 * and avoids remote font fetches at render time.
 */

import { ImageResponse } from "next/og";

/** Standard OG card dimensions (1.91:1). */
export const OG_SIZE = { width: 1200, height: 630 } as const;

/** Content type emitted for every generated card. */
export const OG_CONTENT_TYPE = "image/png";

/** Brand colours, sampled from the `globals.css` HSL tokens. */
const COLORS = {
  background: "#0a0a0b",
  panel: "#111113",
  gold: "#ffd83d",
  foreground: "#f0ede7",
  muted: "#9c988f",
  border: "#2a2a2e",
} as const;

/**
 * Menivor mark (slipped split circle) for OG cards. Mirrors
 * components/brand/MenivorMark.tsx gradient variant and public/brand/*.svg.
 */
function BrandMark() {
  return (
    <svg width="56" height="56" viewBox="0 0 64 64">
      <defs>
        <linearGradient id="og-mv-upper" x1="10" y1="8" x2="44" y2="42" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#ffe992" />
          <stop offset="1" stopColor={COLORS.gold} />
        </linearGradient>
        <linearGradient id="og-mv-lower" x1="22" y1="22" x2="54" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#f0b843" />
          <stop offset="1" stopColor="#c8892e" />
        </linearGradient>
      </defs>
      <path d="M50.34 10.16A25 25 0 0 0 15.16 45.34Z" fill="url(#og-mv-upper)" />
      <path d="M48.84 18.66A25 25 0 0 1 13.66 53.84Z" fill="url(#og-mv-lower)" />
    </svg>
  );
}

interface OgImageParams {
  /** The main headline (e.g. a page title). */
  readonly title: string;
  /** Small eyebrow label above the title. */
  readonly eyebrow?: string;
  /** Bottom-line descriptor. */
  readonly footer?: string;
}

/**
 * Render a branded OG card. Returns an `ImageResponse`, ready to be the default
 * export return value of an `opengraph-image.tsx` route.
 */
export function renderOgImage({
  title,
  eyebrow = "Menivor",
  footer = "menivor.com · AI UGC video generator",
}: OgImageParams): ImageResponse {
  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          backgroundColor: COLORS.background,
          padding: "72px",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <BrandMark />
          <div
            style={{
              display: "flex",
              fontSize: "30px",
              fontWeight: 700,
              color: COLORS.foreground,
              letterSpacing: "-0.02em",
            }}
          >
            {eyebrow}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          <div
            style={{
              display: "flex",
              height: "6px",
              width: "96px",
              backgroundColor: COLORS.gold,
              borderRadius: "999px",
            }}
          />
          <div
            style={{
              display: "flex",
              fontSize: title.length > 48 ? "62px" : "76px",
              fontWeight: 800,
              lineHeight: 1.05,
              letterSpacing: "-0.03em",
              color: COLORS.foreground,
              maxWidth: "1000px",
            }}
          >
            {title}
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: `1px solid ${COLORS.border}`,
            paddingTop: "28px",
          }}
        >
          <div style={{ display: "flex", fontSize: "26px", color: COLORS.muted }}>
            {footer}
          </div>
          <div
            style={{
              display: "flex",
              fontSize: "24px",
              fontWeight: 600,
              color: COLORS.gold,
            }}
          >
            screen recording → finished reel
          </div>
        </div>
      </div>
    ),
    { ...OG_SIZE },
  );
}
