"use client";

import * as React from "react";
import { CalendarClock, CreditCard, Users } from "lucide-react";
import type { Subscription } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { findPlan } from "./plans";
import {
  formatDate,
  intervalLabel,
  statusLabel,
  subscriptionStatusVariant,
} from "./format";

export interface CurrentPlanCardProps {
  /** The live subscription, or `null` when the workspace is on the base plan. */
  subscription: Subscription | null;
  /** Whether the caller may manage billing (`billing.manage`). */
  canManage: boolean;
  /** True while a management mutation is in flight. */
  pending: boolean;
  /** Cancel the subscription (only shown to managers with a live plan). */
  onCancel: () => void;
}

/**
 * Summary of the workspace's current subscription: plan, lifecycle status,
 * cadence, seats, and next renewal. When there is no live subscription the
 * workspace is on the base "Free" plan. Cancel is offered only to callers who
 * hold `billing.manage` and only while a cancellable plan is active. Read-only
 * otherwise — the server remains the source of truth.
 */
export function CurrentPlanCard({
  subscription,
  canManage,
  pending,
  onCancel,
}: Readonly<CurrentPlanCardProps>) {
  const plan = findPlan(subscription?.plan_key) ?? findPlan("free");
  const status = subscription?.status ?? "none";
  const isLive = status === "active" || status === "trialing" || status === "past_due";
  const canCancel = canManage && Boolean(subscription) && isLive;
  const [confirming, setConfirming] = React.useState(false);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="size-5 text-primary" aria-hidden />
              {plan?.name ?? subscription?.plan_key ?? "Free"} plan
            </CardTitle>
            <CardDescription>
              {subscription
                ? "Your workspace's current subscription."
                : "No paid subscription — you're on the base Free plan."}
            </CardDescription>
          </div>
          <Badge variant={subscriptionStatusVariant(status)}>
            {subscription ? statusLabel(status) : "Free"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {subscription ? (
          <dl className="grid gap-4 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Billing cadence</dt>
              <dd className="mt-0.5 text-sm font-medium capitalize">
                {intervalLabel(subscription.interval === "year" ? "year" : "month")}
              </dd>
            </div>
            <div>
              <dt className="flex items-center gap-1 text-xs text-muted-foreground">
                <Users className="size-3" aria-hidden /> Seats
              </dt>
              <dd className="mt-0.5 text-sm font-medium tabular-nums">
                {subscription.seats}
              </dd>
            </div>
            <div>
              <dt className="flex items-center gap-1 text-xs text-muted-foreground">
                <CalendarClock className="size-3" aria-hidden />{" "}
                {isLive ? "Renews" : "Billing period end"}
              </dt>
              <dd className="mt-0.5 text-sm font-medium">
                {formatDate(subscription.current_period_end)}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            Choose a plan below to unlock more credits, seats, and features.
          </p>
        )}

        {status === "past_due" && (
          <p className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            Your last payment failed, so plan features are paused. The payment
            provider retries the charge automatically; use the link in its
            payment email to update your card.
          </p>
        )}

        {canCancel && !confirming && (
          <div className="flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirming(true)}
              disabled={pending}
            >
              Cancel subscription
            </Button>
          </div>
        )}

        {canCancel && confirming && (
          <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-4">
            <p className="text-sm">
              Cancel the {plan?.name ?? "paid"} plan now? The subscription is
              canceled with the payment provider immediately, so you won&apos;t be
              charged again. Plan features end now; credits already in the
              workspace pool stay usable.
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirming(false)}
                disabled={pending}
              >
                Keep plan
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  setConfirming(false);
                  onCancel();
                }}
                disabled={pending}
              >
                Cancel now
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
