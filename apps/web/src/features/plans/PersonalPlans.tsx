"use client";

import { cn } from "@/lib/utils";
import { MonthlyPlansView } from "./MonthlyPlans";
import { MyMonthlyPlanView } from "./MyMonthlyPlan";
import { PremiumPacks } from "./PremiumPacks";
import { usePlans } from "./use-plans";

/**
 * Billing-page block for a creator's own plan: the current plan (renewal date,
 * reels left, cancel, card and invoices) above the plan grid, sharing one
 * fetch so a cancel or switch updates both at once.
 */
export function PersonalPlans({ className }: Readonly<{ className?: string }>) {
  const state = usePlans();
  return (
    <div className={cn("space-y-6", className)}>
      <MyMonthlyPlanView state={state} />
      <MonthlyPlansView state={state} />
      <PremiumPacks />
    </div>
  );
}
