/**
 * What the paywall moment offers (MR2), read from plan config only: the
 * lowest one-time pack first (the default), the lowest monthly plan second.
 * Nothing here types a price.
 */

import type { PricingPlan } from "@/components/marketing/PricingCard";
import { PRICING_PLANS } from "@/components/marketing/plans";
import { formatUsd, type MonthlyCatalog, type PlanKey } from "@/src/features/plans/api";
import type { PackKey } from "@/src/shared/access/api";

/** Where the displayed prices come from (rendered as a data-copy-source marker). */
export const PACK_COPY_SOURCE = "components/marketing/plans.ts";
export const MONTHLY_COPY_SOURCE = "GET /billing/monthly-plans";

export interface PackOffer {
  readonly planKey: PackKey;
  readonly name: string;
  readonly price: string;
  readonly reels: number;
}

export interface MonthlyOffer {
  readonly planKey: PlanKey;
  readonly name: string;
  readonly price: string;
  readonly reels: number;
}

export interface PaywallOffers {
  readonly pack: PackOffer | null;
  readonly monthly: MonthlyOffer | null;
}

function dollars(display: string): number | null {
  const match = /^\$(\d+(?:\.\d{1,2})?)$/.exec(display.trim());
  return match ? Number(match[1]) : null;
}

const PACK_KEYS: readonly string[] = ["starter", "pro"];

export function paywallOffers(
  catalog: MonthlyCatalog,
  packs: readonly PricingPlan[] = PRICING_PLANS,
): PaywallOffers {
  const cheapestPack = packs
    .filter((p) => p.planKey && PACK_KEYS.includes(p.planKey) && (dollars(p.price) ?? 0) > 0)
    .sort((a, b) => (dollars(a.price) ?? 0) - (dollars(b.price) ?? 0))[0];
  const cheapestMonthly = [...catalog.plans]
    .filter((p) => p.available.month)
    .sort((a, b) => a.monthly_cents - b.monthly_cents)[0];
  return {
    pack: cheapestPack
      ? {
          planKey: cheapestPack.planKey as PackKey,
          name: cheapestPack.name,
          price: cheapestPack.price,
          reels: cheapestPack.credits,
        }
      : null,
    monthly: cheapestMonthly
      ? {
          planKey: cheapestMonthly.plan_key,
          name: cheapestMonthly.name,
          price: formatUsd(cheapestMonthly.monthly_cents),
          reels: cheapestMonthly.monthly_reels,
        }
      : null,
  };
}
