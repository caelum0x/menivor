import type { PricingPlan } from "@/components/marketing/PricingCard";
import { OFFER } from "@/lib/offer";

/**
 * PERSONAL credit packs: Free 3 / Starter pack 30 / Pro pack 120. One credit
 * renders one finished 9:16 reel. Packs are ONE-TIME purchases added to the
 * buyer's own balance — distinct from the monthly WORKSPACE plans at /billing
 * (components/billing/plans.ts), which grant a monthly team allotment plus
 * plan entitlements. `planKey` is the backend `plan_key` sent to
 * POST /billing/checkout; the live price/credits come from GET /billing/plans
 * (see live-plans.ts) and override these display defaults.
 *
 * Features list only what a pack actually changes: the number of credits.
 * Plan capabilities (seats, API access, priority rendering, watermark removal)
 * are workspace-plan entitlements and are described there.
 */
export const PRICING_PLANS: readonly PricingPlan[] = [
  {
    name: "Free",
    credits: 3,
    price: "$0",
    period: "to start",
    description: OFFER.freePlan,
    features: [
      OFFER.freePlanFeature,
      "Native 9:16 vertical export",
      "AI-written or your own script",
      "Free AI voice + karaoke captions",
      "Captions over your own video",
    ],
    ctaLabel: "Make my first video",
    ctaHref: "/create",
  },
  {
    name: "Starter pack",
    planKey: "starter",
    credits: 30,
    price: "$19",
    period: "one-time",
    description: "For creators shipping reels every week.",
    features: [
      "30 reel credits",
      "Everything in Free",
      "Turkish & English narration",
      "Added to your personal balance",
      "No subscription — pay once",
    ],
    ctaLabel: "Buy Starter pack",
    highlighted: true,
  },
  {
    name: "Pro pack",
    planKey: "pro",
    credits: 120,
    price: "$59",
    period: "one-time",
    description: "For high-volume publishing at the best per-reel price.",
    features: [
      "120 reel credits",
      "Everything in Starter pack",
      "Lowest price per reel",
      "Added to your personal balance",
      "No subscription — pay once",
    ],
    ctaLabel: "Buy Pro pack",
  },
] as const;
