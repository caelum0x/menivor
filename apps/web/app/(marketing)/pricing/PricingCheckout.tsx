"use client";

import { CheckoutPlans } from "@/components/marketing/CheckoutPlans";
import { LivePackPreview } from "@/components/marketing/LivePackPreview";
import type { PricingPlan } from "@/components/marketing/PricingCard";
import { MonthlyPlans, type MonthlyCatalog } from "@/src/features/plans";
import { PaymentsPausedNotice, usePaymentsMode } from "@/src/shared/payments";

/**
 * Live checkout on /pricing. While payments are paused the buy buttons are
 * replaced by a calm "back soon" notice (with the newsletter signup) and a
 * static pack preview whose only CTA is the free sign-up.
 */
export function PricingCheckout({
  plans,
  monthlyCatalog,
}: Readonly<{ plans: readonly PricingPlan[]; monthlyCatalog?: MonthlyCatalog | null }>) {
  const { mode } = usePaymentsMode();
  if (mode.paused) {
    return (
      <div className="flex flex-col gap-10">
        <PaymentsPausedNotice mode={mode} className="max-w-2xl" />
        <LivePackPreview plans={plans} ctaLabel="Make my first video" ctaHref="/sign-up" />
      </div>
    );
  }
  return (
    <>
      <MonthlyPlans className="mb-14" initialCatalog={monthlyCatalog} />
      <CheckoutPlans plans={plans} />
    </>
  );
}
