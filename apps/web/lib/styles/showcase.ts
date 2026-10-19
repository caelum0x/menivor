/**
 * The landing's showcase reels: one example reel per niche, each a REAL render
 * from Menivor's own pipeline (typed script, free neural voice, word captions,
 * the style's scene). Footage is licensed stock video (Pexels License) or our
 * own rendered loops; two reels advertise our own products from a live
 * recording of their public pages. The businesses in the other reels are
 * examples, and every tile says so.
 *
 * Files: `<base>/<key>.mp4` (540x960 muted H.264 loop), `<key>-poster.jpg`,
 * and the full 720x1280 reel with sound at `<full base>/<key>-full.mp4`.
 *
 * Every file is served from the public media bucket (`menivor-public`) on the
 * custom domain `media.menivor.com`, never from `r2.dev` (rate-limited, not a
 * production origin, and TLS-reset on some networks). The loop and poster
 * also ship in `public/samples/showcase`, the fallback when the media domain
 * fails. Publishing: `apps/api/tools/ops/showcase/publish.py`.
 */

import { REEL_STYLES, findStyle, type ReelStyle, type StyleId } from "./catalog";

/** The public media origin (bucket `menivor-public`). */
export const MEDIA_ORIGIN = "https://media.menivor.com";

/** Where a base URL may point: our media domain, or a same-origin path. Never r2.dev. */
export function mediaBase(raw: string | undefined, fallback: string): string {
  const value = (raw ?? "").trim().replace(/\/+$/, "");
  if (!value || /(^|\.|\/\/)r2\.dev(\/|$)/i.test(value)) return fallback;
  return value;
}

/** Muted loops and posters. */
export const SHOWCASE_BASE_URL = mediaBase(
  process.env.NEXT_PUBLIC_SHOWCASE_BASE_URL,
  `${MEDIA_ORIGIN}/showcase`,
);

/** Full reels with sound. */
export const SHOWCASE_FULL_BASE_URL = mediaBase(
  process.env.NEXT_PUBLIC_SHOWCASE_FULL_BASE_URL,
  `${MEDIA_ORIGIN}/showcase`,
);

/** Same-origin copies of every loop and poster (the fallback source). */
export const SHOWCASE_LOCAL_BASE_URL = "/samples/showcase";

/** Wall groups, in page order. */
export type ShowcaseGroup = "shops" | "life";

export const SHOWCASE_GROUPS: readonly {
  readonly id: ShowcaseGroup;
  readonly title: string;
  readonly subline: string;
}[] = [
  {
    id: "shops",
    title: "Products and shops",
    subline: "Skincare, sneakers, software, cafes, barbers and florists. A page in, a reel out.",
  },
  {
    id: "life",
    title: "Food, travel, fitness and homes",
    subline: "Recipes, trips, training plans, house tours and home services, in every style.",
  },
];

export interface ShowcaseReel {
  readonly key: string;
  /** What the example business or creator does. */
  readonly niche: string;
  /** The style the reel was made with (null: the plain voiceover reel). */
  readonly styleId: StyleId | null;
  /** The opening line on screen (each reel has its own). */
  readonly hook: string;
  readonly group: ShowcaseGroup;
  /** Our own product, when the reel advertises one (at most two reels). */
  readonly ownProduct?: string;
  /** Where the footage comes from (honest labelling). */
  readonly footage: "stock" | "page";
}

/** The plain voiceover reel: full-screen footage, voice and word captions. */
export const VOICEOVER_LABEL = "Voiceover reel";

/**
 * Every showcase reel, hero first. Keys are file names; order is display order
 * within each group.
 */
export const SHOWCASE_REELS: readonly ShowcaseReel[] = [
  { key: "island-drone", niche: "Island travel guide", styleId: null, group: "life", footage: "stock",
    hook: "Save this for the trip you keep putting off." },
  { key: "serum-morning", niche: "Skincare brand", styleId: null, group: "shops", footage: "stock",
    hook: "This serum is the only step I never skip." },
  { key: "ring-pov", niche: "Jewelry shop", styleId: "pov_text", group: "shops", footage: "stock",
    hook: "POV: you finally found a ring you never take off" },
  { key: "sneaker-meme", niche: "Sneaker brand", styleId: "meme_hook", group: "shops", footage: "stock",
    hook: "Nobody: Me buying the same sneakers in a third colour" },
  { key: "saas-inbox", niche: "Help desk software", styleId: "gameplay_split", group: "shops", footage: "stock",
    hook: "Tell me you answer every support email without telling me" },
  { key: "candle-split", niche: "Handmade candles", styleId: "satisfying_split", group: "shops", footage: "stock",
    hook: "Here is what nobody tells you about hand-poured candles" },
  { key: "menivor-pov", niche: "Menivor", styleId: "pov_text", group: "shops", footage: "page",
    ownProduct: "Menivor", hook: "POV: you pasted one link and got three reels back" },
  { key: "scribase-split", niche: "Scribase", styleId: "satisfying_split", group: "shops", footage: "page",
    ownProduct: "Scribase", hook: "Here is what nobody tells you about shipping your app backend" },
  { key: "latte-cafe", niche: "Corner cafe", styleId: null, group: "shops", footage: "stock",
    hook: "Every cup at our corner cafe gets poured by hand." },
  { key: "barber-meme", niche: "Barber shop", styleId: "meme_hook", group: "shops", footage: "stock",
    hook: "You met me at a very overgrown time in my life" },
  { key: "burger-pov", niche: "Burger grill", styleId: "pov_text", group: "shops", footage: "stock",
    hook: "POV: you walked past our grill at lunchtime" },
  { key: "bakery-morning", niche: "Bakery", styleId: null, group: "shops", footage: "stock",
    hook: "Our bread comes out of the oven before the sun is up." },
  { key: "car-before-after", niche: "Car detailing", styleId: "before_after", group: "life", footage: "stock",
    hook: "Before: road salt, dull paint, brake dust. After: a finish you can see yourself in." },
  { key: "dog-groom-split", niche: "Pet grooming", styleId: "satisfying_split", group: "shops", footage: "stock",
    hook: "Nobody tells you how calm a dog can be at the groomer" },
  { key: "florist-story", niche: "Flower shop", styleId: "story_gameplay", group: "shops", footage: "stock",
    hook: "I opened a tiny flower shop and this is what a Friday looks like" },
  { key: "power-wash", niche: "Exterior cleaning", styleId: null, group: "life", footage: "stock",
    hook: "Watch years of grime come off in one pass." },
  { key: "cleaning-before-after", niche: "Home cleaning", styleId: "before_after", group: "life", footage: "stock",
    hook: "Before: a weekend lost to chores. After: a spotless home and your Saturday back." },
  { key: "paint-meme", niche: "Art class", styleId: "meme_hook", group: "life", footage: "stock",
    hook: "Me after one beginner painting class thinking I am an artist now" },
  { key: "pasta-weeknight", niche: "Weeknight recipes", styleId: null, group: "life", footage: "stock",
    hook: "The weeknight pasta I make when I am too tired to cook." },
  { key: "smoothie-split", niche: "Smoothie recipes", styleId: "satisfying_split", group: "life", footage: "stock",
    hook: "Here is the smoothie bowl nobody tells you how to get thick" },
  { key: "cooking-narrator", niche: "Cooking class", styleId: "character_story", group: "life", footage: "stock",
    hook: "I signed up for a pasta class and it changed my Sundays" },
  { key: "gym-split", niche: "Fitness coach", styleId: "gameplay_split", group: "life", footage: "stock",
    hook: "POV: your training plan finally fits your week" },
  { key: "trail-story", niche: "Running club", styleId: "story_gameplay", group: "life", footage: "stock",
    hook: "I joined a running club to meet people and ended up loving the trail" },
  { key: "tokyo-meme", niche: "City night tours", styleId: "meme_hook", group: "life", footage: "stock",
    hook: "Me pretending I will sleep early on my first night in Tokyo" },
  { key: "hike-pov", niche: "Hiking tours", styleId: "pov_text", group: "life", footage: "stock",
    hook: "POV: you said yes to the sunrise hike" },
  { key: "house-tour", niche: "Real estate agent", styleId: null, group: "life", footage: "stock",
    hook: "Walk through this home with me." },
  { key: "kitchen-before-after", niche: "Interior designer", styleId: "before_after", group: "life",
    footage: "stock",
    hook: "Before: a dark kitchen nobody wanted to cook in. After: the room everyone ends up in." },
];

/**
 * Keys whose `-full.mp4` (the 720x1280 reel with sound) does not exist in
 * either the public media bucket or the private bucket's legacy upload path
 * (confirmed via `publish.py --verify` and a direct bucket listing, 2026-10-17
 * — the source render was never re-uploaded after the bucket migration and is
 * gone from both buckets, so there is nothing to re-publish). Every other
 * asset for these reels (the muted loop, the poster) is present and fine.
 * `toMedia` reports `full: null` for these so the UI never links to the 404:
 * the sound-toggle button simply does not render for them, and the expanded
 * player opens the muted loop instead of bouncing off a failed request first.
 */
export const SHOWCASE_MISSING_FULL_KEYS: ReadonlySet<string> = new Set([
  "tokyo-meme",
  "saas-inbox",
  "barber-meme",
  "bakery-morning",
  "car-before-after",
  "dog-groom-split",
  "florist-story",
  "power-wash",
  "candle-split",
  "paint-meme",
  "cleaning-before-after",
  "menivor-pov",
  "scribase-split",
]);

export interface ShowcaseMedia extends ShowcaseReel {
  /** The preset name shown on the tile. */
  readonly label: string;
  readonly mp4: string;
  readonly poster: string;
  /** `null` when the full reel with sound is missing (see `SHOWCASE_MISSING_FULL_KEYS`). */
  readonly full: string | null;
  /** Same-origin copies used when the media domain fails to load. */
  readonly fallbackMp4: string;
  readonly fallbackPoster: string;
}

export function showcaseLabel(reel: Pick<ShowcaseReel, "styleId">): string {
  return reel.styleId ? findStyle(reel.styleId)?.label ?? VOICEOVER_LABEL : VOICEOVER_LABEL;
}

function toMedia(reel: ShowcaseReel): ShowcaseMedia {
  return {
    ...reel,
    label: showcaseLabel(reel),
    mp4: `${SHOWCASE_BASE_URL}/${reel.key}.mp4`,
    poster: `${SHOWCASE_BASE_URL}/${reel.key}-poster.jpg`,
    full: SHOWCASE_MISSING_FULL_KEYS.has(reel.key)
      ? null
      : `${SHOWCASE_FULL_BASE_URL}/${reel.key}-full.mp4`,
    fallbackMp4: `${SHOWCASE_LOCAL_BASE_URL}/${reel.key}.mp4`,
    fallbackPoster: `${SHOWCASE_LOCAL_BASE_URL}/${reel.key}-poster.jpg`,
  };
}

/** The honest one-line caption under a tile. */
export function showcaseCredit(reel: ShowcaseReel): string {
  if (reel.ownProduct) return `Our own product, from its live page`;
  return `Example ${reel.niche.toLowerCase()}, stock footage`;
}

export interface ShowcaseLayout {
  readonly hero: ShowcaseMedia;
  /** Two more reels beside the hero on wide screens. */
  readonly heroSide: readonly ShowcaseMedia[];
  readonly groups: readonly { readonly id: ShowcaseGroup; readonly title: string;
    readonly subline: string; readonly reels: readonly ShowcaseMedia[] }[];
}

/**
 * Splits the showcase so NO reel appears twice on the page: the hero, two
 * side reels, then every other reel in its group wall.
 */
export function showcaseLayout(): ShowcaseLayout {
  const all = SHOWCASE_REELS.map(toMedia);
  const [hero, ...rest] = all;
  if (!hero) throw new Error("showcase needs at least one reel");
  const sideKeys = new Set(["serum-morning", "tokyo-meme"]);
  const heroSide = rest.filter((reel) => sideKeys.has(reel.key));
  const remaining = rest.filter((reel) => !sideKeys.has(reel.key));
  const groups = SHOWCASE_GROUPS.map((group) => ({
    ...group,
    reels: remaining.filter((reel) => reel.group === group.id),
  })).filter((group) => group.reels.length > 0);
  return { hero, heroSide, groups };
}

/** Every showcase reel with its media URLs, in catalog order. */
export function showcaseMedia(): ShowcaseMedia[] {
  return SHOWCASE_REELS.map(toMedia);
}

/** Showcase reels made in one style (the style gallery's cards). */
export function showcaseFor(id: StyleId): ShowcaseMedia[] {
  return showcaseMedia().filter((reel) => reel.styleId === id);
}

/** Styles with at least one showcase reel (the style gallery shows only these). */
export function showcaseStyles(): ReelStyle[] {
  return REEL_STYLES.filter((style) => SHOWCASE_REELS.some((reel) => reel.styleId === style.id));
}

export interface StyleGalleryAllocation {
  /** One lead reel per style card. */
  readonly cards: readonly { readonly style: ReelStyle; readonly reel: ShowcaseMedia }[];
  /** Every reel not used by a card. */
  readonly rest: readonly ShowcaseMedia[];
}

/** The /styles page split: each style's first reel on its card, the rest below. */
export function allocateStyleGallery(): StyleGalleryAllocation {
  const used = new Set<string>();
  const cards = showcaseStyles().flatMap((style) => {
    const reel = showcaseFor(style.id)[0];
    if (!reel) return [];
    used.add(reel.key);
    return [{ style, reel }];
  });
  return { cards, rest: showcaseMedia().filter((reel) => !used.has(reel.key)) };
}
