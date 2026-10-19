import type { MetadataRoute } from "next";

const SITE_URL = "https://menivor.com";

/**
 * Auth pages and app surfaces (signed-in or device-session) that must never be
 * crawled. The public marketing surface (landing, pricing, the /editor landing,
 * /showcase (templates section only), and every programmatic /tools,
 * /features, /guides, /for, /make and /video-ads page) is allowed by the `/`
 * rule. Prefixes match like robots.txt: "/ads" also covers "/ads/new"; none
 * of them prefixes a marketing route.
 */
const DISALLOW = [
  "/api/",
  // Auth pages: nothing to rank, and they would compete with the landing page.
  "/sign-in",
  "/sign-up",
  // The create flow and every signed-in or device-session app surface. The
  // bare "/create" is matched exactly so "/creators/" profiles stay crawlable.
  "/create$",
  "/create/",
  "/ab-lab",
  "/account",
  "/ad-studio",
  "/admin",
  "/ads",
  "/agency",
  "/analytics",
  "/approvals",
  "/avatars",
  "/batch/",
  "/beta",
  "/billing",
  "/blueprints",
  "/brand$", // page only; /brand/* are public logo assets
  "/broll",
  "/calendar",
  "/captions",
  "/capture",
  "/catalog",
  "/channels",
  "/characters",
  "/clipmarket",
  "/connections",
  "/dashboard",
  "/developer",
  "/discover",
  "/effects-lab",
  "/film",
  "/filtergraph",
  "/gateway",
  "/hook-finder",
  "/hook-lab",
  "/ideas",
  "/import",
  "/inbox",
  "/insights",
  "/invite",
  "/jobs",
  "/marketplace",
  "/media",
  "/model-governance",
  "/motion",
  "/new",
  "/notifications",
  "/onboarding",
  "/performance",
  "/presets",
  "/projects",
  "/publish",
  "/r/",
  "/reels",
  "/referral",
  "/render",
  "/retention-lab",
  "/scheduled",
  "/settings",
  // NOTE: "/showcase" is intentionally NOT disallowed. Its real-reels wall and
  // templates section (viral shot-template gallery) are public marketing
  // content with no auth required and ship their own
  // SoftwareApplication/Organization JSON-LD for indexing; only the "your
  // completed reels" sub-section is sign-in gated client-side, so crawlers
  // see the same safe, auth-free view as a logged-out visitor. See
  // app/(marketing)/showcase/page.tsx.
  "/spend",
  "/studio",
  "/team",
  "/trend-lab",
  "/trends",
  "/uploads",
  "/usage",
  "/voices",
  "/wallet",
  "/workflows-lab",
  "/workspace",
];

/**
 * AI answer-engine crawlers. Explicitly allowing them is a low-cost GEO
 * (generative-engine optimisation) play: the tools, features and guides pages
 * are structured for citation in AI answers.
 */
const AI_CRAWLERS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended"];

/**
 * Dynamic robots.txt (Next.js App Router). Allows crawling of the public
 * marketing surface while disallowing the authenticated app surfaces.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: DISALLOW,
      },
      ...AI_CRAWLERS.map((userAgent) => ({
        userAgent,
        allow: "/",
        disallow: DISALLOW,
      })),
    ],
    sitemap: [`${SITE_URL}/sitemap.xml`, `${SITE_URL}/video-sitemap.xml`],
    host: SITE_URL,
  };
}
