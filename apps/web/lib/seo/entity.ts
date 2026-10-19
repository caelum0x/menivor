/**
 * Menivor's entity graph (MB1): the Organization, WebSite and
 * SoftwareApplication JSON-LD the root layout renders on every page.
 *
 * Honesty rules, each enforced by `entity.test.ts`:
 * - No price is typed here. Every `Offer` price is read from plan config: the
 *   sign-up offer (`lib/offer.ts`), the personal packs
 *   (`components/marketing/plans.ts`) and the monthly plans
 *   (`src/features/plans/api.ts`, shown only while on sale).
 * - `sameAs` lists only handles marked `live` in {@link BRAND_HANDLES}. A
 *   handle is marked live only after someone opened it and saw the Menivor
 *   profile (MB4 keeps the list in `gtm/brand/handles.md`).
 * - No legal name and no founder: company and founder wording is owner item 17.
 *   Until it is answered the graph names the product only
 *   ({@link OWNER_ITEM_17_PENDING}).
 */

import { PRICING_PLANS } from "@/components/marketing/plans";
import { OFFER, PAYMENTS_PAUSED } from "@/lib/offer";
import { FALLBACK_CATALOG, type MonthlyCatalog } from "@/src/features/plans/api";
import { MENIVOR_ONE_LINER, SITE_URL } from "./site";

/** Company and founder names wait for owner item 17 (legal name, public founder name). */
export const OWNER_ITEM_17_PENDING = true;

export const ENTITY_DESCRIPTION =
  "Menivor is AI video software that turns a link or a topic into ready-to-post vertical reels.";

/** The 50-word description every directory and press listing copies (MB2). */
export const PRESS_DESCRIPTION_SHORT =
  "Menivor is AI video software that turns a link or a topic into ready-to-post vertical reels. Paste a product page or type an idea, and Menivor writes a hook-first script, adds an AI voiceover and word-by-word captions, and renders three 9:16 variants with different opening hooks.";

/** The 150-word description (MB2). */
export const PRESS_DESCRIPTION_LONG =
  "Menivor is AI video software that turns a link or a topic into ready-to-post vertical reels for TikTok, Instagram Reels and YouTube Shorts. Paste a product page, a store listing or an article, or type an idea, and Menivor writes a hook-first script in English or Turkish, adds a natural AI voiceover and word-by-word karaoke captions, and renders three 9:16 variants that open with different hooks, so you can post the one that fits. You can also add captions to a video you recorded yourself. Every reel is a finished 1080 x 1920 MP4 you download and own. Pricing is simple: a small card check unlocks free reels, then one-time credit packs or a monthly plan. Credits do not expire, and a render that fails gives its credit back. AI agents can drive Menivor through its MCP server. Menivor is made by the team behind Scribase and Rally.";

export const SUPPORT_EMAIL = "support@menivor.com";
export const LOGO_PATH = "/brand/menivor-mark-512.png";

export interface BrandHandle {
  readonly platform: string;
  readonly url: string;
  /** True only after the profile was opened and shows Menivor (MB4). */
  readonly live: boolean;
}

/**
 * The checked-in handle list. None is confirmed yet (MB4 is an owner sign-up
 * step), so `sameAs` renders nothing until a row is flipped to `live: true`.
 */
export const BRAND_HANDLES: readonly BrandHandle[] = [
  { platform: "TikTok", url: "https://www.tiktok.com/@menivor", live: false },
  { platform: "Instagram", url: "https://www.instagram.com/menivor", live: false },
  { platform: "YouTube", url: "https://www.youtube.com/@menivor", live: false },
  { platform: "X", url: "https://x.com/menivor", live: false },
  { platform: "LinkedIn", url: "https://www.linkedin.com/company/menivor", live: false },
  { platform: "GitHub", url: "https://github.com/menivor", live: false },
  { platform: "Product Hunt", url: "https://www.producthunt.com/products/menivor", live: false },
];

export function liveHandles(handles: readonly BrandHandle[] = BRAND_HANDLES): string[] {
  return handles.filter((h) => h.live).map((h) => h.url);
}

/** "$19" -> 19; anything that is not a plain dollar amount -> null. */
export function dollarsFrom(display: string): number | null {
  const match = /^\$(\d+(?:\.\d{1,2})?)$/.exec(display.trim());
  return match ? Number(match[1]) : null;
}

/** schema.org wants a plain decimal string. */
function priceString(dollars: number): string {
  return dollars.toFixed(2);
}

/** The sign-up card check amount, read from the offer copy (null while payments are paused). */
export function cardCheckDollars(copy: string = OFFER.signupSubheading): number | null {
  const match = /\$(\d+(?:\.\d{1,2})?) card check/.exec(copy);
  return match ? Number(match[1]) : null;
}

export interface OfferLd {
  readonly "@type": "Offer";
  readonly name: string;
  readonly price: string;
  readonly priceCurrency: "USD";
  readonly description: string;
  readonly url: string;
}

export interface OfferSources {
  readonly paymentsPaused: boolean;
  readonly cardCheck: number | null;
  readonly packs: typeof PRICING_PLANS;
  readonly monthly: MonthlyCatalog;
}

const DEFAULT_SOURCES: OfferSources = {
  paymentsPaused: PAYMENTS_PAUSED,
  cardCheck: cardCheckDollars(),
  packs: PRICING_PLANS,
  monthly: FALLBACK_CATALOG,
};

/**
 * Offer rows from plan config: the card check (with its free reels), the
 * lowest one-time pack, and the lowest monthly plan when it is on sale.
 */
export function offersFromPlanConfig(sources: OfferSources = DEFAULT_SOURCES): OfferLd[] {
  const url = `${SITE_URL}/pricing`;
  const offers: OfferLd[] = [];
  const free = sources.packs.find((p) => dollarsFrom(p.price) === 0);
  if (!sources.paymentsPaused && free && sources.cardCheck) {
    offers.push({
      "@type": "Offer",
      name: "Card check",
      price: priceString(sources.cardCheck),
      priceCurrency: "USD",
      description: `A one-time card check unlocks ${free.credits} free reels and becomes 1 more reel credit.`,
      url,
    });
  }
  const paidPacks = sources.packs
    .map((p) => ({ plan: p, dollars: dollarsFrom(p.price) }))
    .filter((p): p is { plan: (typeof PRICING_PLANS)[number]; dollars: number } => (p.dollars ?? 0) > 0)
    .sort((a, b) => a.dollars - b.dollars);
  const lowestPack = paidPacks[0];
  if (lowestPack) {
    offers.push({
      "@type": "Offer",
      name: lowestPack.plan.name,
      price: priceString(lowestPack.dollars),
      priceCurrency: "USD",
      description: `${lowestPack.plan.credits} reel credits, one-time purchase; credits do not expire.`,
      url,
    });
  }
  const monthly = [...sources.monthly.plans]
    .filter((p) => p.available.month)
    .sort((a, b) => a.monthly_cents - b.monthly_cents)[0];
  if (monthly) {
    offers.push({
      "@type": "Offer",
      name: `${monthly.name} monthly plan`,
      price: priceString(monthly.monthly_cents / 100),
      priceCurrency: "USD",
      description: `${monthly.monthly_reels} reels a month, billed monthly.`,
      url,
    });
  }
  return offers;
}

export function organizationLd(handles: readonly BrandHandle[] = BRAND_HANDLES) {
  const sameAs = liveHandles(handles);
  return {
    "@type": "Organization",
    "@id": `${SITE_URL}/#organization`,
    name: "Menivor",
    alternateName: "Menivor AI",
    url: SITE_URL,
    logo: `${SITE_URL}${LOGO_PATH}`,
    description: ENTITY_DESCRIPTION,
    contactPoint: {
      "@type": "ContactPoint",
      contactType: "customer support",
      email: SUPPORT_EMAIL,
    },
    ...(sameAs.length ? { sameAs } : {}),
  } as const;
}

export function softwareApplicationEntity(
  description: string = MENIVOR_ONE_LINER,
  sources: OfferSources = DEFAULT_SOURCES,
) {
  const offers = offersFromPlanConfig(sources);
  return {
    "@type": "SoftwareApplication",
    name: "Menivor",
    applicationCategory: "MultimediaApplication",
    operatingSystem: "Web",
    url: SITE_URL,
    description,
    brand: { "@id": `${SITE_URL}/#organization` },
    ...(offers.length ? { offers } : {}),
  } as const;
}

/** The root-layout graph. WebSite has no SearchAction: the site has no search. */
export function siteEntityGraph(sources: OfferSources = DEFAULT_SOURCES) {
  return {
    "@context": "https://schema.org",
    "@graph": [
      organizationLd(),
      {
        "@type": "WebSite",
        "@id": `${SITE_URL}/#website`,
        url: SITE_URL,
        name: "Menivor",
        publisher: { "@id": `${SITE_URL}/#organization` },
      },
      softwareApplicationEntity(
        "AI short video generator: paste a link or type a topic and get three vertical reels with different hooks, an AI voiceover and word-by-word captions, or add captions to your own video.",
        sources,
      ),
    ],
  } as const;
}

/** Every price the plan config can produce (the test's allow-list). */
export function planConfigPrices(sources: OfferSources = DEFAULT_SOURCES): Set<string> {
  const prices = new Set<string>();
  if (sources.cardCheck) prices.add(priceString(sources.cardCheck));
  for (const p of sources.packs) {
    const d = dollarsFrom(p.price);
    if (d !== null) prices.add(priceString(d));
  }
  for (const p of sources.monthly.plans) prices.add(priceString(p.monthly_cents / 100));
  return prices;
}
