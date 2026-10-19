"use client";

import * as React from "react";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { signUpHref } from "@/lib/auth-redirect";
import { cn } from "@/lib/utils";
import {
  changePlan,
  formatUsd,
  planErrorMessage,
  savingsVsPacks,
  startPlanCheckout,
  type MonthlyCatalog,
  type MonthlyPlan,
  type PlanInterval,
} from "./api";
import { usePlans, type PlansState } from "./use-plans";
import { OverageToggle, overageDisclosure, useOverageTerms } from "./OverageConsent";
import { PaymentsPausedNotice, providerLabel, usePaymentsMode } from "@/src/shared/payments";

/** Where signed-out visitors return after sign-up. */
const RETURN_PATH = "/pricing";

function PlanCard({
  plan,
  interval,
  state,
  highlighted,
}: Readonly<{ plan: MonthlyPlan; interval: PlanInterval; state: PlansState; highlighted: boolean }>) {
  const { catalog, mine, signedIn, getToken, setMine } = state;
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const current = mine?.plan ?? null;
  const isCurrent = current?.plan_key === plan.plan_key;
  const yearly = interval === "year";
  const price = yearly ? plan.yearly_cents : plan.monthly_cents;
  const reels = yearly ? plan.yearly_reels : plan.monthly_reels;
  const saving = savingsVsPacks(plan, interval, catalog.best_pack_per_reel_cents);
  const available = plan.available[current ? current.interval : interval];

  const act = async () => {
    setError("");
    if (!signedIn) {
      window.location.assign(signUpHref(RETURN_PATH));
      return;
    }
    setBusy(true);
    try {
      const token = await getToken();
      if (current) {
        setMine(await changePlan(plan.plan_key, { token }));
        setBusy(false);
        return;
      }
      const { checkout_url: url } = await startPlanCheckout(plan.plan_key, interval, { token });
      window.location.assign(url);
    } catch (err) {
      setError(planErrorMessage(err));
      setBusy(false);
    }
  };

  const label = isCurrent
    ? "Your plan"
    : current
      ? `Switch to ${plan.name}`
      : available
        ? `Start ${plan.name}`
        : "Not on sale yet";

  return (
    <li
      className={cn(
        "flex flex-col gap-4 rounded-lg border p-5",
        highlighted ? "border-primary/60 bg-primary/5" : "border-border",
      )}
    >
      <div className="space-y-1">
        <p className="text-sm font-medium">{plan.name}</p>
        <p className="text-3xl font-semibold tracking-tight">
          {formatUsd(price)}
          <span className="text-sm font-normal text-muted-foreground">/{yearly ? "year" : "month"}</span>
        </p>
        <p className="text-sm text-muted-foreground">
          {reels} reels {yearly ? "a year" : "a month"}, {formatUsd(plan.per_reel_cents[interval])} per reel
        </p>
      </div>
      <ul className="space-y-1.5 text-sm">
        {[
          saving > 0 ? `${saving}% less per reel than credit packs` : "Monthly reels at a fixed price",
          yearly ? "All 12 months of reels added up front" : "Reels added on every renewal",
          "Every format your account can make",
          "Cancel in one click, keep reels to period end",
        ].map((line) => (
          <li key={line} className="flex items-start gap-2">
            <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            <span>{line}</span>
          </li>
        ))}
      </ul>
      <Button
        type="button"
        className="mt-auto"
        variant={highlighted && !isCurrent ? "default" : "outline"}
        disabled={busy || isCurrent || !available}
        onClick={() => void act()}
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
        {label}
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </li>
  );
}

/**
 * The monthly plans with a Monthly / Yearly toggle. Subscribers see their plan
 * marked and can switch in one click; everyone else subscribes in one click
 * (signed-out visitors sign up first and come back here).
 */
export function MonthlyPlans({
  className,
  initialCatalog,
}: Readonly<{ className?: string; initialCatalog?: MonthlyCatalog | null }>) {
  const state = usePlans(initialCatalog);
  return <MonthlyPlansView state={state} className={className} />;
}

/** The plan grid over a shared {@link PlansState} (one fetch per page). */
export function MonthlyPlansView({
  state,
  className,
}: Readonly<{ state: PlansState; className?: string }>) {
  const [interval, setBillingInterval] = React.useState<PlanInterval>("month");
  const recommended = state.mine?.plan ? null : (state.mine?.recommended_plan ?? "pro");
  const subscriber = Boolean(state.mine?.plan);
  const { mode } = usePaymentsMode();
  const overage = useOverageTerms();
  const myPlan = state.mine?.plan ?? null;
  const shownInterval: PlanInterval = subscriber ? (myPlan?.interval ?? "month") : interval;

  if (mode.paused && !subscriber) {
    return (
      <section className={cn("space-y-4", className)} aria-labelledby="monthly-plans-title">
        <h2 id="monthly-plans-title" className="text-xl font-semibold tracking-tight">
          Monthly plans
        </h2>
        <PaymentsPausedNotice mode={mode} />
      </section>
    );
  }

  return (
    <section className={cn("space-y-5", className)} aria-labelledby="monthly-plans-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 id="monthly-plans-title" className="text-xl font-semibold tracking-tight">
            Monthly plans
          </h2>
          <p className="text-sm text-muted-foreground">
            The cheapest way to make reels every month. Packs stay available for top-ups.
          </p>
        </div>
        {subscriber ? null : (
          <div role="group" aria-label="Billing period" className="inline-flex rounded-md border border-border p-0.5">
            {(["month", "year"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={interval === value}
                onClick={() => setBillingInterval(value)}
                className={cn(
                  "rounded px-3 py-1.5 text-sm",
                  interval === value ? "bg-primary text-primary-foreground" : "text-muted-foreground",
                )}
              >
                {value === "month" ? "Monthly" : "Yearly, 2 months free"}
              </button>
            ))}
          </div>
        )}
      </div>
      <ul className="grid gap-4 md:grid-cols-3">
        {state.catalog.plans.map((plan) => (
          <PlanCard
            key={plan.plan_key}
            plan={plan}
            interval={shownInterval}
            state={state}
            highlighted={plan.plan_key === (state.mine?.plan?.plan_key ?? recommended)}
          />
        ))}
      </ul>
      {myPlan && overage && mode.provider === "dodo" ? (
        <OverageToggle
          terms={overage}
          planKey={myPlan.plan_key}
          planName={myPlan.name}
          interval={myPlan.interval}
          getToken={state.getToken}
        />
      ) : null}
      <p className="text-xs text-muted-foreground">
        Plans renew automatically every {interval === "year" && !subscriber ? "year" : "month"} at the price
        shown until you cancel. Cancel anytime in one click from Billing; you keep your reels until the
        paid period ends. Included reels are used first and do not roll over. Credit packs never
        expire. Switching up charges the difference for the current period and adds the extra reels
        right away. {overageDisclosure(mode.provider === "dodo" ? overage : null, shownInterval)} Payments by {providerLabel(mode.provider)}.
      </p>
    </section>
  );
}
