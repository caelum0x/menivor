"use client";

import * as React from "react";
import Link from "next/link";
import { Check, Sparkles } from "lucide-react";
import { RefreshCw, Users } from "lucide-react";
import type {
  PaymentProvider,
  SubscribeRequest,
  SubscriptionInterval,
  SubscriptionProvider,
} from "@/lib/types";
import { WAITLIST_FALLBACK_EMAIL } from "@/lib/waitlist";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ProviderToggle } from "@/components/marketing/ProviderToggle";
import { cn } from "@/lib/utils";
import { BILLING_PLANS, type BillingPlan, planRank } from "./plans";
import { formatCents, intervalSuffix } from "./format";
import {
  mergeWorkspaceCatalog,
  offerFor,
  providersFor,
  useWorkspacePlanCatalog,
} from "./live-plans";

const SALES_EMAIL = WAITLIST_FALLBACK_EMAIL;

export interface PlanGridProps {
  /** The workspace's current plan key (`"free"` when on the base plan). */
  currentPlanKey: string;
  /** Whether a live paid subscription exists (drives subscribe vs switch). */
  hasSubscription: boolean;
  /** Whether the caller may manage billing (`billing.manage`). */
  canManage: boolean;
  /** True while a billing mutation is in flight (disables CTAs). */
  pending: boolean;
  /** Start a new subscription (hosted checkout on the chosen rail) for a plan. */
  onSubscribe: (body: SubscribeRequest) => void;
  /** Switch an existing subscription to another plan. */
  onChangePlan: (planKey: string) => void;
  /**
   * Why a new subscription checkout is unavailable right now (launch gate),
   * or "" / undefined when checkout is open. Plan switches are unaffected.
   */
  checkoutClosedReason?: string;
}

/**
 * The plan catalog: a monthly/yearly toggle and a payment-rail picker (for a
 * new subscription, limited to the rails the backend has configured for that
 * interval), then a card per plan with LIVE prices, credits and included seats
 * from `GET /billing/workspace-plans`. The CTA adapts to the workspace's
 * current plan — "Current", "Subscribe", "Upgrade"/"Downgrade" (a downgrade to
 * Free asks for confirmation because it cancels the paid plan), or "Contact
 * sales" for Enterprise. Non-managers see the cards read-only with a hint to
 * ask a billing admin; the server enforces `billing.manage` regardless.
 */
export function PlanGrid({
  currentPlanKey,
  hasSubscription,
  canManage,
  pending,
  onSubscribe,
  onChangePlan,
  checkoutClosedReason = "",
}: Readonly<PlanGridProps>) {
  const [interval, setInterval] = React.useState<SubscriptionInterval>("month");
  const catalog = useWorkspacePlanCatalog();
  const plans = React.useMemo(
    () => mergeWorkspaceCatalog(BILLING_PLANS, catalog.offers),
    [catalog.offers],
  );

  // Rails that can sell at least one paid plan at the chosen interval.
  const intervalProviders = React.useMemo<readonly SubscriptionProvider[]>(() => {
    const seen = new Set<SubscriptionProvider>();
    for (const offer of catalog.offers) {
      for (const p of offer.providers[interval]) seen.add(p);
    }
    return (["stripe", "creem", "polar"] as const).filter((p) => seen.has(p));
  }, [catalog.offers, interval]);

  const [provider, setProvider] = React.useState<SubscriptionProvider | null>(null);
  React.useEffect(() => {
    setProvider((current) =>
      current && intervalProviders.includes(current)
        ? current
        : (intervalProviders[0] ?? null),
    );
  }, [intervalProviders]);

  const currentRank = planRank(currentPlanKey);
  const choosingNew = !hasSubscription && canManage;

  return (
    <div className="space-y-6">
      {!hasSubscription && (
        <div className="flex flex-wrap items-end justify-between gap-4">
          <IntervalToggle value={interval} onChange={setInterval} />
          {choosingNew && (
            <div className="flex flex-col items-start gap-1.5">
              <span className="text-sm font-medium">Pay with</span>
              {catalog.status === "loading" ? (
                <Skeleton className="h-9 w-48 rounded-lg" />
              ) : catalog.status === "error" ? (
                <button
                  type="button"
                  onClick={catalog.reload}
                  className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
                >
                  <RefreshCw className="size-3.5" aria-hidden /> Couldn&apos;t load
                  payment options. Retry
                </button>
              ) : intervalProviders.length > 0 && provider ? (
                <ProviderToggle
                  value={provider as PaymentProvider}
                  providers={intervalProviders}
                  onChange={(next) => setProvider(next as SubscriptionProvider)}
                  disabled={pending}
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {interval === "year" ? "Yearly" : "Monthly"} billing isn&apos;t
                  available yet.{" "}
                  <a
                    href={`mailto:${SALES_EMAIL}?subject=Menivor%20workspace%20plan`}
                    className="font-medium text-primary underline underline-offset-4"
                  >
                    Email us
                  </a>{" "}
                  to set up a plan.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {plans.map((plan) => {
          const offer = offerFor(catalog.offers, plan.key);
          const sellable =
            provider !== null &&
            providersFor(catalog.offers, plan.key, interval).includes(provider);
          return (
            <PlanCard
              key={plan.key}
              plan={plan}
              interval={interval}
              maxSeats={offer?.max_seats ?? null}
              isCurrent={plan.key === currentPlanKey.toLowerCase()}
              currentRank={currentRank}
              hasSubscription={hasSubscription}
              canManage={canManage}
              pending={pending}
              purchasable={sellable}
              blockedReason={checkoutClosedReason}
              onSubscribe={() => {
                if (!provider || !sellable || checkoutClosedReason) return;
                onSubscribe({
                  plan_key: plan.key,
                  interval,
                  seats: Math.max(1, offer?.max_seats ?? 1),
                  provider,
                });
              }}
              onChangePlan={() => onChangePlan(plan.key)}
            />
          );
        })}
      </div>

      {hasSubscription && canManage && (
        <p className="text-xs text-muted-foreground">
          Switching between paid plans updates your subscription with the
          payment provider right away. The price difference is prorated and
          charged now, and an upgrade adds the extra credits for the current
          period to the pool.
        </p>
      )}
    </div>
  );
}

interface IntervalToggleProps {
  value: SubscriptionInterval;
  onChange: (value: SubscriptionInterval) => void;
}

/** Segmented monthly/yearly control. Yearly advertises the two-months-free win. */
function IntervalToggle({ value, onChange }: Readonly<IntervalToggleProps>) {
  return (
    <div
      className="inline-flex items-center rounded-lg border border-border bg-secondary/30 p-1"
      role="group"
      aria-label="Billing cadence"
    >
      {(["month", "year"] as const).map((option) => {
        const isActive = value === option;
        return (
          <button
            key={option}
            type="button"
            aria-pressed={isActive}
            onClick={() => onChange(option)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option === "month" ? "Monthly" : "Yearly"}
            {option === "year" && (
              <span className="ml-1.5 text-xs text-success">2 months free</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

interface PlanCardProps {
  plan: BillingPlan;
  interval: SubscriptionInterval;
  /** Seats included in the plan (from the live catalog), or `null` if unknown. */
  maxSeats: number | null;
  /** Whether the selected rail can sell this plan at this interval. */
  purchasable: boolean;
  isCurrent: boolean;
  currentRank: number;
  hasSubscription: boolean;
  canManage: boolean;
  pending: boolean;
  /** Launch-gate reason a new subscription cannot start now ("" when open). */
  blockedReason?: string;
  onSubscribe: () => void;
  onChangePlan: () => void;
}

function priceLabel(plan: BillingPlan, interval: SubscriptionInterval): string {
  const cents = interval === "year" ? plan.yearlyCents : plan.monthlyCents;
  if (cents === null) return "Custom";
  if (cents === 0) return "Free";
  return formatCents(cents);
}

function PlanCard({
  plan,
  interval,
  maxSeats,
  purchasable,
  isCurrent,
  currentRank,
  hasSubscription,
  canManage,
  pending,
  blockedReason = "",
  onSubscribe,
  onChangePlan,
}: Readonly<PlanCardProps>) {
  const isEnterprise = plan.monthlyCents === null;
  const price = priceLabel(plan, interval);
  const showSuffix = !isEnterprise && plan.monthlyCents !== 0;

  return (
    <Card
      className={cn(
        "flex flex-col",
        plan.highlighted && "border-primary ring-1 ring-primary/30",
        isCurrent && "bg-secondary/20",
      )}
    >
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div>
          <div className="flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 font-semibold">
              {plan.highlighted && (
                <Sparkles className="size-4 text-primary" aria-hidden />
              )}
              {plan.name}
            </h3>
            {isCurrent && (
              <Badge variant="secondary" className="shrink-0">
                Current
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {plan.description}
          </p>
        </div>

        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-bold tracking-tight tabular-nums">
            {price}
          </span>
          {showSuffix && (
            <span className="text-sm text-muted-foreground">
              {intervalSuffix(interval)}
            </span>
          )}
        </div>

        {maxSeats !== null && plan.monthlyCents !== 0 && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Users className="size-3.5" aria-hidden />
            Includes up to {maxSeats} {maxSeats === 1 ? "seat" : "seats"}
          </p>
        )}

        <ul className="flex-1 space-y-2 text-sm">
          {plan.features.map((feature) => (
            <li key={feature} className="flex items-start gap-2">
              <Check
                className="mt-0.5 size-4 shrink-0 text-success"
                aria-hidden
              />
              <span>{feature}</span>
            </li>
          ))}
        </ul>

        <PlanCta
          plan={plan}
          isCurrent={isCurrent}
          currentRank={currentRank}
          isEnterprise={isEnterprise}
          hasSubscription={hasSubscription}
          canManage={canManage}
          pending={pending}
          purchasable={purchasable}
          blockedReason={blockedReason}
          onSubscribe={onSubscribe}
          onChangePlan={onChangePlan}
        />
      </CardContent>
    </Card>
  );
}

interface PlanCtaProps {
  plan: BillingPlan;
  purchasable: boolean;
  isCurrent: boolean;
  currentRank: number;
  isEnterprise: boolean;
  hasSubscription: boolean;
  canManage: boolean;
  pending: boolean;
  /** Launch-gate reason a new subscription cannot start now ("" when open). */
  blockedReason?: string;
  onSubscribe: () => void;
  onChangePlan: () => void;
}

/** The per-plan action, resolved from the caller's rights and current plan. */
function PlanCta({
  plan,
  purchasable,
  isCurrent,
  currentRank,
  isEnterprise,
  hasSubscription,
  canManage,
  pending,
  blockedReason = "",
  onSubscribe,
  onChangePlan,
}: Readonly<PlanCtaProps>) {
  const [confirming, setConfirming] = React.useState(false);

  if (isCurrent) {
    return (
      <Button variant="outline" size="sm" disabled className="w-full">
        Current plan
      </Button>
    );
  }

  if (isEnterprise) {
    return (
      <Button asChild variant="outline" size="sm" className="w-full">
        <Link href={`mailto:${SALES_EMAIL}?subject=Menivor%20Enterprise`}>
          Contact sales
        </Link>
      </Button>
    );
  }

  if (!canManage) {
    return (
      <p className="text-center text-xs text-muted-foreground">
        Ask a billing admin to change plans.
      </p>
    );
  }

  // A live subscription switches plans in place; otherwise start checkout.
  if (hasSubscription) {
    const direction =
      plan.rank > currentRank
        ? "Upgrade"
        : plan.rank < currentRank
          ? "Downgrade"
          : "Switch";
    if (plan.monthlyCents === 0 && confirming) {
      // Stepping down to Free cancels the paid subscription at the provider.
      return (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            This cancels the paid plan now. No further charges; credits already
            in the pool stay usable.
          </p>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              size="sm"
              className="flex-1"
              disabled={pending}
              onClick={() => {
                setConfirming(false);
                onChangePlan();
              }}
            >
              Cancel paid plan
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              disabled={pending}
              onClick={() => setConfirming(false)}
            >
              Keep it
            </Button>
          </div>
        </div>
      );
    }
    return (
      <Button
        variant={plan.rank > currentRank ? "default" : "outline"}
        size="sm"
        className="w-full"
        disabled={pending}
        onClick={plan.monthlyCents === 0 ? () => setConfirming(true) : onChangePlan}
      >
        {direction} to {plan.name}
      </Button>
    );
  }

  if (plan.monthlyCents === 0) {
    // Free is the base every workspace falls back to; nothing to buy.
    return (
      <Button variant="outline" size="sm" disabled className="w-full">
        Included
      </Button>
    );
  }

  return (
    <Button
      variant={plan.highlighted ? "default" : "outline"}
      size="sm"
      className="w-full"
      disabled={pending || !purchasable || Boolean(blockedReason)}
      onClick={onSubscribe}
      title={
        blockedReason
          ? blockedReason
          : purchasable
            ? undefined
            : "Not available with this payment option"
      }
    >
      {plan.rank > currentRank ? "Upgrade" : "Subscribe"}
    </Button>
  );
}
