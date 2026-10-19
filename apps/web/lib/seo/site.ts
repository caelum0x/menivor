/**
 * Shared, static product facts for the programmatic SEO engine.
 *
 * Everything here is grounded in `docs/menivor.md` (the product/competitor
 * research doc) and the shipped code — no invented metrics. These constants are
 * the single source of truth consumed by the tool, feature, and guide pages
 * plus the sitemap, so copy and differentiators stay consistent across the
 * whole surface.
 */

import { WAITLIST_MODE } from "@/lib/clerk";
import { WAITLIST_ANCHOR } from "@/lib/waitlist";
import type { LaunchMode } from "@/src/shared/launch-posture/posture";
import { OFFER } from "@/lib/offer";

export const SITE_URL = "https://menivor.com";

/** Keep search snippets concise while preserving complete words. */
export function compactSeoDescription(
  value: string,
  maxLength = 155,
): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;

  const candidate = normalized.slice(0, maxLength - 1);
  const lastWordBoundary = candidate.lastIndexOf(" ");
  const ending =
    lastWordBoundary >= Math.floor(maxLength * 0.75)
      ? candidate.slice(0, lastWordBoundary)
      : candidate;
  return `${ending.trimEnd()}…`;
}

/** One-sentence product definition reused in metadata + JSON-LD descriptions. */
export const MENIVOR_ONE_LINER =
  "Menivor turns a link or a topic into finished, ready-to-post 1080×1920 short videos: an AI hook script (English or Turkish), a natural AI voiceover, original footage or your own screen recording, and word-by-word karaoke captions.";

/** The pipeline, described the same way the landing page + docs describe it. */
export const MENIVOR_PIPELINE =
  "link, topic or screen recording → hook-first script (English or Turkish) → AI voiceover → original footage or your recording → word-by-word karaoke captions → finished 9:16 MP4 to download and post on TikTok, Instagram Reels and YouTube Shorts.";

/**
 * Menivor's honest, capability-based differentiators. These describe what the
 * product does — they deliberately avoid user/revenue claims, because Menivor
 * has not published those numbers.
 */
export interface Differentiator {
  readonly key: string;
  readonly title: string;
  readonly body: string;
}

export const MENIVOR_DIFFERENTIATORS: readonly Differentiator[] = [
  {
    key: "link-or-topic",
    title: "One input: a link or a topic",
    body: "Paste a product link and get ads written for it. Type a topic and get a story or a series. Menivor writes, voices, captions and renders the finished videos; there is no timeline to edit.",
  },
  {
    key: "original-footage",
    title: "Original footage, safe to post",
    body: "Gameplay and satisfying loops are rendered by us, story scenes are generated fresh for each video, and your own screen recording can be the footage. No ripped clips or library sounds.",
  },
  {
    key: "karaoke-captions",
    title: "Word-by-word karaoke captions",
    body: "Word-by-word captions are burned in, timed off word-level voice timestamps as the single timing source — so captions land exactly on the spoken word.",
  },
  {
    key: "success-only-billing",
    title: "Success-only credits",
    body: "One credit renders one finished reel. Credits are reserved when a render starts, captured only when it succeeds, and released back to you if it fails. Buy packs that never expire, or a monthly plan for a lower price per reel.",
  },
  {
    key: "template-marketplace",
    title: "Template marketplace with a win-score",
    body: "Publish, clone, rate, and remix reel templates that are ranked by a win-score fed from real, self-reported reel outcomes through the Hook Performance Loop.",
  },
  {
    key: "idea-engine",
    title: "SPARK idea engine",
    body: "Pull new hook ideas from the SPARK idea engine instead of starting from a blank page, then download finished reels ready to post on TikTok, Instagram Reels and YouTube Shorts.",
  },
];

/**
 * The dimensions used to build every comparison table. `menivor` is Menivor's
 * honest value for the row; each competitor supplies its own value in
 * `Competitor.comparison`. Keeping the axes in one place makes every /vs and
 * /alternatives table consistent and easy to scan.
 */
export interface ComparisonDimension {
  readonly key: string;
  readonly label: string;
  readonly menivor: string;
}

export const COMPARISON_DIMENSIONS: readonly ComparisonDimension[] = [
  {
    key: "primaryJob",
    label: "Primary job",
    menivor: "Finished short videos from a link, a topic or a screen recording",
  },
  {
    key: "captions",
    label: "Captions",
    menivor: "Word-by-word karaoke, burned in and timed to the audio",
  },
  {
    key: "languages",
    label: "Script languages",
    menivor: "Scripts, voiceovers, and captions in English or Turkish",
  },
  {
    key: "billing",
    label: "Billing model",
    menivor: "Monthly plans or pay-per-reel packs; failed renders are refunded",
  },
  {
    key: "freeTier",
    label: "Free tier",
    menivor: OFFER.short,
  },
] as const;

export interface Cta {
  readonly href: string;
  readonly label: string;
}

/**
 * Canonical primary CTA for a launch mode (see src/shared/launch-posture):
 * the waitlist while WAITLIST_MODE is on or the launch status is unreadable,
 * the early-access request during a private beta, and free signup once the
 * API reports public access with signup open. Never a dead page.
 */
export function primaryCtaFor(mode: LaunchMode): Cta {
  if (mode === "public") return { href: "/sign-up", label: "Make my first video" };
  if (mode === "beta") return { href: "/beta", label: "Request early access" };
  return { href: `/#${WAITLIST_ANCHOR}`, label: "Join the waitlist" };
}

/**
 * Static default for surfaces that cannot read the launch status. Server
 * pages should prefer `primaryCtaFor((await getLaunchPosture()).mode)`.
 */
export const PRIMARY_CTA: Cta = primaryCtaFor(WAITLIST_MODE ? "waitlist" : "public");

export const SECONDARY_CTA = {
  href: "/pricing",
  label: "See pricing",
} as const;
