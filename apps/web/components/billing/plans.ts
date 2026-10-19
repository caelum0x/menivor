import type { PlanKey } from "@/lib/types";

/**
 * Display catalog for the workspace SUBSCRIPTION plans (Epic 3 billing). These
 * are recurring team plans — NOT the one-time personal credit packs sold on
 * /pricing and /wallet/plans (components/marketing/plans.ts). Feature bullets
 * list only what the API enforces today (monthly credit allotment + metering);
 * see app/services/entitlements.py before adding capability claims. The
 * BACKEND is always the source of truth for money at checkout and for the live
 * entitlement bundle (`GET /me/workspaces/{id}/entitlements`) — these values are
 * display-only copy so the plan cards render without a round-trip. Prices are
 * integer minor units (cents); `null` means "talk to us" (Enterprise) and is
 * never sent as a numeric amount. Keys mirror `PlanKey` /
 * `app.services.entitlements.PLAN_ENTITLEMENTS`.
 */
export interface BillingPlan {
  key: PlanKey;
  name: string;
  description: string;
  /** Monthly price in cents, or `null` for custom (Enterprise). */
  monthlyCents: number | null;
  /** Yearly price in cents (billed once a year), or `null` for custom. */
  yearlyCents: number | null;
  /** Reel credits granted per billing month for this plan. */
  monthlyCredits: number;
  /** Short, human feature bullets (display-only mirror of entitlements). */
  features: readonly string[];
  /** Relative rank used to label a switch as an upgrade vs a downgrade. */
  rank: number;
  /** Visually emphasize this card as the recommended plan. */
  highlighted?: boolean;
}

/**
 * The subscribable plans, cheapest → richest. `free` is the implicit base a
 * workspace falls back to when it has no live subscription, so it has no paid
 * checkout. Enterprise routes to sales (custom pricing) rather than self-serve
 * checkout.
 */
export const BILLING_PLANS: readonly BillingPlan[] = [
  {
    key: "free",
    name: "Free",
    description: "Try the full pipeline on a few reels each month.",
    monthlyCents: 0,
    yearlyCents: 0,
    monthlyCredits: 3,
    rank: 0,
    features: [
      "3 reel credits / month",
      "Native 9:16 vertical export",
      "AI voice + karaoke captions",
      "Usage metering",
    ],
  },
  {
    key: "starter",
    name: "Team Starter",
    description: "For creators shipping reels every week.",
    monthlyCents: 1900,
    yearlyCents: 19000,
    monthlyCredits: 30,
    rank: 1,
    features: [
      "30 reel credits / month",
      "Shared workspace credit pool",
      "Usage metering & invoices",
      "Monthly, or yearly with 2 months free",
    ],
  },
  {
    key: "pro",
    name: "Team Pro",
    description: "For teams publishing at high volume.",
    monthlyCents: 5900,
    yearlyCents: 59000,
    monthlyCredits: 120,
    rank: 2,
    highlighted: true,
    features: [
      "120 reel credits / month",
      "Everything in Starter",
      "Lowest per-reel price on a plan",
      "Monthly, or yearly with 2 months free",
    ],
  },
  {
    key: "enterprise",
    name: "Enterprise",
    description: "SSO, SCIM, custom limits, and a dedicated contact.",
    monthlyCents: null,
    yearlyCents: null,
    monthlyCredits: 1000,
    rank: 3,
    features: [
      "Custom credit allotment",
      "SSO & SCIM provisioning",
      "Audit log & data retention controls",
      "Priority support & SLA",
    ],
  },
] as const;

/** Look up a plan by key (case-insensitive), or `null` when unknown. */
export function findPlan(planKey: string | null | undefined): BillingPlan | null {
  if (!planKey) return null;
  const key = planKey.toLowerCase();
  return BILLING_PLANS.find((p) => p.key === key) ?? null;
}

/** The rank of a plan key (defaults to the base `free` rank when unknown). */
export function planRank(planKey: string | null | undefined): number {
  return findPlan(planKey)?.rank ?? 0;
}
