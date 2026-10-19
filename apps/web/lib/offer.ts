/**
 * The sign-up offer, in one place. Normally a $1 card check (charged by our
 * payment provider and turned into 1 reel credit) unlocks 3 free reels. When
 * payments are paused (`NEXT_PUBLIC_MENIVOR_PAYMENTS_PAUSED=1` at build time,
 * matching the API's MENIVOR_PAYMENTS_PAUSED) there is no card step: every
 * account gets free reels each month instead.
 */

export const PAYMENTS_PAUSED = process.env.NEXT_PUBLIC_MENIVOR_PAYMENTS_PAUSED === "1";

/**
 * The first reel is free before the card check (API `MENIVOR_FREE_FIRST_REEL=1`).
 * On by default; build with `NEXT_PUBLIC_MENIVOR_FREE_FIRST_REEL=0` when the API
 * flag is off so the copy never promises a reel the server will not grant.
 */
export const FREE_FIRST_REEL = process.env.NEXT_PUBLIC_MENIVOR_FREE_FIRST_REEL !== "0";

const CARD = {
  /** Sub-heading under most marketing CTAs. */
  signupSubheading: "Sign up free. A $1 card check unlocks 3 free reels, and the $1 becomes 1 more reel.",
  /** Short hero note. */
  heroNote: "Sign up free. A $1 card check unlocks 3 free reels.",
  /** Sign-up page line after "One click with Google or Apple." */
  signupNext: "Next, a $1 card check unlocks 3 free reels, and the $1 becomes a fourth.",
  /** How-it-works step. */
  howStep: "One click with Google or Apple, then a $1 card check that becomes a reel credit. The reels start by themselves.",
  /** Business-page CTA sub-heading. */
  startSubheading: "Paste the link, approve the $1 card check, and three reels start rendering. Credits never expire.",
  /** Free plan card description. */
  freePlan: "3 free reels after a $1 card check, plus 1 more for the $1.",
  /** Free plan card first feature line. */
  freePlanFeature: "3 reel credits, plus 1 for the $1 check",
  /** Very short tagline. */
  short: "3 free reels after a $1 card check",
  /** Public launch body. */
  publicBody:
    "Menivor is open to everyone on the free tier. Create a free account, unlock 3 free reels with a $1 card check, and start with the formats that are live today.",
  /** Public launch step. */
  publicStep: "Sign up in one click with Google or Apple. A $1 card check unlocks 3 free reels, and the $1 becomes 1 more reel.",
  /** Pricing explainer lead sentence. */
  pricingLead: "New accounts unlock three free reels with a $1 card check, and the $1 becomes a fourth reel.",
  /** FAQ: is it free. */
  faqFree:
    "Yes. Menivor is open to everyone on the free tier. Creating an account is free, and a $1 card check unlocks your free reels.",
  /** SEO use-case: what you get free (videos wording). */
  seoFreeVideos: "New accounts unlock three free AI UGC videos with a $1 card check, and the $1 becomes a fourth video.",
  /** SEO use-case FAQ answer lead. */
  seoFaqFree: "Yes. New Menivor accounts unlock three free reels with a $1 card check, and the $1 becomes a fourth reel.",
} as const;

type OfferCopy = { readonly [K in keyof typeof CARD]: string };

const PAUSED: OfferCopy = {
  signupSubheading: "Sign up free and get 3 free reels every month. No card needed.",
  heroNote: "Sign up free. 3 free reels every month, no card needed.",
  signupNext: "Then you get 3 free reels every month, no card needed.",
  howStep: "One click with Google or Apple. No card needed. The reels start by themselves.",
  startSubheading: "Paste the link and three free reels start rendering. No card needed.",
  freePlan: "3 free reels every month, no card needed.",
  freePlanFeature: "3 reel credits every month",
  short: "3 free reels every month",
  publicBody:
    "Menivor is open to everyone on the free tier. Create a free account, get 3 free reels every month, and start with the formats that are live today.",
  publicStep: "Sign up in one click with Google or Apple and get 3 free reels every month. No card needed.",
  pricingLead: "Every account gets three free reels a month while paid plans are paused.",
  faqFree: "Yes. Menivor is open to everyone on the free tier. Creating an account is free and includes 3 free reels every month.",
  seoFreeVideos: "Every account gets three free AI UGC videos a month.",
  seoFaqFree: "Yes. Every Menivor account gets three free reels a month.",
};

/** Card-check offer with the free first reel up front (same promises, plus one reel). */
const FIRST_REEL: OfferCopy = {
  ...CARD,
  signupSubheading:
    "Sign up free and make your first reel free, no card. Then a $1 card check unlocks 3 more free reels, and the $1 becomes 1 more reel.",
  heroNote: "Your first reel is free, no card. A $1 card check then unlocks 3 more.",
  signupNext: "Your first reel is free, no card. After it, a $1 card check unlocks 3 more free reels, and the $1 becomes a fifth.",
  publicStep:
    "Sign up in one click with Google or Apple and make your first reel free, no card. A $1 card check then unlocks 3 more free reels, and the $1 becomes 1 more reel.",
  short: "First reel free, no card",
  howStep:
    "One click with Google or Apple and your first reel renders free, no card. A $1 card check then unlocks 3 more free reels and becomes a reel credit.",
  startSubheading:
    "Paste the link and your first reel renders free, no card. A $1 card check then unlocks three hook versions per run. Credits never expire.",
  freePlan: "First reel free with no card. A $1 card check then adds 3 free reels, plus 1 more for the $1.",
  freePlanFeature: "1 free reel, then 3 more plus 1 for the $1 check",
  publicBody:
    "Menivor is open to everyone on the free tier. Create a free account, make your first reel free with no card, then unlock 3 more free reels with a $1 card check.",
  pricingLead:
    "New accounts make their first reel free with no card. A $1 card check then unlocks three more free reels, and the $1 becomes a fifth reel.",
  faqFree:
    "Yes. Menivor is open to everyone on the free tier. Creating an account is free, your first reel is free with no card, and a $1 card check unlocks 3 more.",
  seoFreeVideos:
    "New accounts make their first AI UGC video free with no card, then unlock three more with a $1 card check, and the $1 becomes a fifth video.",
  seoFaqFree:
    "Yes. New Menivor accounts make their first reel free with no card, then unlock three more free reels with a $1 card check, and the $1 becomes a fifth reel.",
};

/** The active offer copy. */
export const OFFER: OfferCopy = PAYMENTS_PAUSED ? PAUSED : FREE_FIRST_REEL ? FIRST_REEL : CARD;
