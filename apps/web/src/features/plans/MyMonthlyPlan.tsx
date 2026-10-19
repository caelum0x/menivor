"use client";

import * as React from "react";
import { CalendarClock, ExternalLink, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  cancelPlan,
  formatDate,
  formatUsd,
  openBillingPortal,
  planErrorMessage,
  type MyPlan,
} from "./api";
import { usePlans, type PlansState } from "./use-plans";

/** Pure: the renewal line shown under the plan name. */
export function renewalLine(mine: MyPlan): string {
  const date = formatDate(mine.current_period_end);
  if (!mine.plan) return "";
  const price = `${formatUsd(mine.plan.price_cents)}/${mine.plan.interval}`;
  if (mine.status === "past_due") {
    return `Your last ${price} payment did not go through. Update your card to keep your plan.`;
  }
  if (mine.renews) {
    return date ? `Renews ${date} at ${price}.` : `Renews automatically at ${price}.`;
  }
  return date
    ? `Renewal is off. Your plan and its reels stay until ${date}; nothing else is charged.`
    : "Renewal is off. Nothing else is charged.";
}

/**
 * The signed-in creator's personal monthly plan: price, renewal date, included
 * reels left, one-click renewal off, and the provider's billing portal (card,
 * invoices). Renders nothing for people without a plan (the plan grid sells).
 */
export function MyMonthlyPlan({ className }: Readonly<{ className?: string }>) {
  const state = usePlans();
  return <MyMonthlyPlanView state={state} className={className} />;
}

/** The plan card over a shared {@link PlansState}. */
export function MyMonthlyPlanView({
  state,
  className,
}: Readonly<{ state: PlansState; className?: string }>) {
  const { mine, getToken, setMine } = state;
  const [busy, setBusy] = React.useState<"cancel" | "portal" | null>(null);
  const [error, setError] = React.useState("");
  if (!mine?.plan) return null;
  const { plan } = mine;

  const cancel = async () => {
    setError("");
    setBusy("cancel");
    try {
      const token = await getToken();
      setMine(await cancelPlan({ token }));
    } catch (err) {
      setError(planErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const portal = async () => {
    setError("");
    setBusy("portal");
    try {
      const token = await getToken();
      const { url } = await openBillingPortal({ token });
      window.location.assign(url);
    } catch (err) {
      setError(planErrorMessage(err));
      setBusy(null);
    }
  };

  return (
    <section
      className={cn("flex flex-col gap-4 rounded-lg border border-primary/40 bg-primary/5 p-5", className)}
      aria-labelledby="my-monthly-plan-title"
      data-testid="my-monthly-plan"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Your monthly plan</p>
          <h2 id="my-monthly-plan-title" className="text-xl font-semibold tracking-tight">
            {plan.name}, {plan.period_reels} reels a {plan.interval}
          </h2>
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarClock className="size-4 shrink-0" aria-hidden />
            {renewalLine(mine)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-3xl font-semibold tabular-nums">{mine.credits}</p>
          <p className="text-xs text-muted-foreground">
            reels available, {mine.included_left} of them from this {plan.interval}
          </p>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Included reels are used first and do not roll over. Credit packs you bought never expire.
      </p>
      <div className="flex flex-wrap gap-2">
        {mine.renews ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={() => void cancel()}
          >
            {busy === "cancel" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            Cancel renewal
          </Button>
        ) : null}
        {mine.can_manage ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy !== null}
            onClick={() => void portal()}
          >
            {busy === "portal" ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <ExternalLink className="size-4" aria-hidden />
            )}
            Manage or cancel subscription
          </Button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </section>
  );
}
