import { apiRequest } from "@/src/shared/api";
import type { Plan } from "@/lib/types";
import { formatCents } from "@/components/billing/format";
import type { PricingPlan } from "@/components/marketing/PricingCard";

/**
 * GET /billing/plans read ANONYMOUSLY (pricing is public; no device session is
 * minted just to show prices). The backend catalog is the single source of
 * truth for what a `plan_key` pack costs and grants; the marketing copy only
 * supplies names, descriptions and feature bullets.
 */
export async function fetchPublicPackCatalog(): Promise<readonly Plan[]> {
  const data = await apiRequest<Plan[] | { plans?: Plan[] }>("/billing/plans", {
    anonymous: true,
  });
  if (Array.isArray(data)) return data;
  return data?.plans ?? [];
}

function livePrice(plan: Readonly<Plan>): string | null {
  if (typeof plan.price === "string" && plan.price.trim()) return plan.price.trim();
  if (typeof plan.amount === "number" && Number.isFinite(plan.amount)) {
    return formatCents(plan.amount, plan.currency);
  }
  return null;
}

/**
 * Overlay live price + credit count onto the display plans by `planKey`.
 * Plans the backend no longer sells are dropped so a stale card can never
 * start a checkout for a retired pack. Returns the input unchanged when the
 * catalog is empty (unreachable API: the server still validates at checkout).
 */
export function mergeLiveCatalog(
  plans: readonly PricingPlan[],
  catalog: readonly Plan[],
): readonly PricingPlan[] {
  if (catalog.length === 0) return plans;
  const byKey = new Map(catalog.map((p) => [p.plan_key.toLowerCase(), p]));
  return plans.flatMap((plan): PricingPlan[] => {
    if (!plan.planKey) return [plan];
    const live = byKey.get(plan.planKey.toLowerCase());
    if (!live) return [];
    const credits =
      typeof live.credits === "number" && live.credits > 0 ? live.credits : plan.credits;
    return [
      {
        ...plan,
        credits,
        price: livePrice(live) ?? plan.price,
        features: plan.features.map((feature) =>
          feature.endsWith(" reel credits") ? `${credits} reel credits` : feature,
        ),
      },
    ];
  });
}
