"use client";

import * as React from "react";
import { PricingCard, type PricingPlan } from "@/components/marketing/PricingCard";
import {
  fetchPublicPackCatalog,
  mergeLiveCatalog,
} from "@/components/marketing/live-plans";

interface LivePackPreviewProps {
  readonly plans: readonly PricingPlan[];
  readonly ctaLabel: string;
  readonly ctaHref: string;
}

/**
 * Read-only pack grid for the waitlist phase. Prices and credit counts are
 * overlaid from the live `GET /billing/plans` catalog (the same source checkout
 * charges from), so a preview can never advertise a different price than the
 * one a buyer will pay once checkout opens. Falls back to the display defaults
 * when the API is unreachable.
 */
export function LivePackPreview({ plans, ctaLabel, ctaHref }: LivePackPreviewProps) {
  const [livePlans, setLivePlans] = React.useState<readonly PricingPlan[]>(plans);

  React.useEffect(() => {
    let active = true;
    void fetchPublicPackCatalog()
      .then((catalog) => {
        if (active) setLivePlans(mergeLiveCatalog(plans, catalog));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [plans]);

  return (
    <div className="grid w-full grid-cols-1 gap-6 md:grid-cols-3 md:items-stretch">
      {livePlans.map((plan) => (
        <PricingCard key={plan.name} plan={{ ...plan, ctaLabel, ctaHref }} />
      ))}
    </div>
  );
}
