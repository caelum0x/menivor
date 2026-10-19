"use client";

import * as React from "react";
import { apiRequest } from "@/src/shared/api";
import type {
  SubscriptionInterval,
  SubscriptionProvider,
  WorkspacePlanOffer,
} from "@/lib/types";
import type { BillingPlan } from "./plans";

const SUBSCRIPTION_PROVIDERS: readonly SubscriptionProvider[] = [
  "stripe",
  "creem",
  "polar",
];

/**
 * GET /billing/workspace-plans, read anonymously (plan prices are public). The
 * backend is the source of truth for what each recurring plan costs, how many
 * credits and seats it includes, and which payment rails are configured to
 * sell it for each billing interval.
 */
export async function fetchWorkspacePlanCatalog(): Promise<
  readonly WorkspacePlanOffer[]
> {
  const data = await apiRequest<
    WorkspacePlanOffer[] | { plans?: WorkspacePlanOffer[] }
  >("/billing/workspace-plans", { anonymous: true });
  const list = Array.isArray(data) ? data : (data?.plans ?? []);
  return list.map((offer) => ({
    ...offer,
    providers: {
      month: knownProviders(offer.providers?.month),
      year: knownProviders(offer.providers?.year),
    },
  }));
}

function knownProviders(
  list: readonly string[] | undefined,
): SubscriptionProvider[] {
  const known = new Set<string>(SUBSCRIPTION_PROVIDERS);
  return (list ?? []).filter((p): p is SubscriptionProvider => known.has(p));
}

export type CatalogStatus = "loading" | "ready" | "error";

export interface WorkspacePlanCatalog {
  status: CatalogStatus;
  offers: readonly WorkspacePlanOffer[];
  reload: () => void;
}

/** Loads the live workspace plan catalog once per mount (with a retry hook). */
export function useWorkspacePlanCatalog(): WorkspacePlanCatalog {
  const [status, setStatus] = React.useState<CatalogStatus>("loading");
  const [offers, setOffers] = React.useState<readonly WorkspacePlanOffer[]>([]);
  const [nonce, setNonce] = React.useState(0);
  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  React.useEffect(() => {
    let active = true;
    setStatus("loading");
    fetchWorkspacePlanCatalog()
      .then((next) => {
        if (!active) return;
        setOffers(next);
        setStatus("ready");
      })
      .catch(() => {
        if (active) setStatus("error");
      });
    return () => {
      active = false;
    };
  }, [nonce]);

  return { status, offers, reload };
}

/** The live offer for a display plan, or `undefined` when not self-serve. */
export function offerFor(
  offers: readonly WorkspacePlanOffer[],
  planKey: string,
): WorkspacePlanOffer | undefined {
  const key = planKey.toLowerCase();
  return offers.find((offer) => offer.plan_key.toLowerCase() === key);
}

/**
 * Overlay live prices and credit allotments onto the display plans. Paid plans
 * the backend does not sell self-serve keep their card but lose their price
 * claim only when the catalog loaded and omitted them.
 */
export function mergeWorkspaceCatalog(
  plans: readonly BillingPlan[],
  offers: readonly WorkspacePlanOffer[],
): readonly BillingPlan[] {
  if (offers.length === 0) return plans;
  return plans.map((plan) => {
    const offer = offerFor(offers, plan.key);
    if (!offer) return plan;
    return {
      ...plan,
      monthlyCents: offer.monthly_cents,
      yearlyCents: offer.yearly_cents,
      monthlyCredits: offer.monthly_credits,
      features: plan.features.map((feature) =>
        feature.endsWith(" reel credits / month")
          ? `${offer.monthly_credits} reel credits / month`
          : feature,
      ),
    };
  });
}

/** Rails that can sell `planKey` at `interval` right now (may be empty). */
export function providersFor(
  offers: readonly WorkspacePlanOffer[],
  planKey: string,
  interval: SubscriptionInterval,
): readonly SubscriptionProvider[] {
  return offerFor(offers, planKey)?.providers[interval] ?? [];
}
