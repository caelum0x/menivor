"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CreditCard,
  Plus,
  RefreshCw,
  Settings,
} from "lucide-react";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { saveCheckoutIntent } from "@/lib/checkout-intent";
import type { SubscribeRequest } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { CurrentPlanCard } from "@/components/billing/CurrentPlanCard";
import { PlanGrid } from "@/components/billing/PlanGrid";
import { UsageMeters } from "@/components/billing/UsageMeters";
import { EntitlementsCard } from "@/components/billing/EntitlementsCard";
import { InvoicesCard } from "@/components/billing/InvoicesCard";
import { BillingHelp } from "@/components/billing/BillingHelp";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { useWorkspacePermissions } from "@/lib/use-workspace-permissions";
import { useWorkspaceBilling } from "@/lib/use-workspace-billing";
import { LaunchGateNotice, useLaunchGate } from "@/src/shared/launch-gate";
import { CreemReturnNotice } from "@/src/shared/access";
import { PersonalPlans } from "@/src/features/plans";

/**
 * ENTERPRISE — Workspace billing (Epic 3). Shows the workspace's current plan,
 * the plan catalog (subscribe / upgrade / downgrade with a monthly-yearly toggle
 * and seats), metered usage vs entitlements, plan features, and invoices. Every
 * surface is TENANT-SCOPED to the selected workspace: subscription management +
 * invoices require `billing.manage`; usage, entitlements, and plan browsing are
 * open to any member. No credits are granted here — checkout hands off to Stripe
 * and the idempotent webhook fulfils the plan. Another tenant's data is never
 * shown.
 */
export default function BillingPage() {
  const { status: wsStatus, workspaces, errorMessage: wsError } =
    useMyWorkspaces();

  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  React.useEffect(() => {
    const first = workspaces[0];
    if (!first) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!workspaces.some((w) => w.id === selectedId)) setSelectedId(first.id);
  }, [workspaces, selectedId]);

  const perms = useWorkspacePermissions(selectedId);
  const canManage = perms.has("billing.manage");
  const billing = useWorkspaceBilling(selectedId, canManage);

  const launch = useLaunchGate();
  const checkoutClosedReason =
    launch.status === "loading"
      ? "Checking whether checkout is open."
      : launch.gate.checkout.open
        ? ""
        : launch.gate.checkout.reason;

  const currentPlanKey = billing.subscription?.plan_key
    ? String(billing.subscription.plan_key)
    : billing.entitlements?.plan_key
      ? String(billing.entitlements.plan_key)
      : "free";
  const liveStatus = billing.subscription?.status;
  const hasSubscription =
    Boolean(billing.subscription) &&
    (liveStatus === "active" ||
      liveStatus === "trialing" ||
      liveStatus === "past_due");

  const handleSubscribe = React.useCallback(
    (body: SubscribeRequest) => {
      void (async () => {
        try {
          const result = await billing.subscribe(body);
          const url = result?.checkout_url;
          if (url && typeof window !== "undefined") {
            saveCheckoutIntent({
              kind: "subscription",
              planKey: body.plan_key,
              baselineCredits: null,
            });
            window.location.assign(url);
          }
        } catch {
          // billing.actionError already carries the reason for display.
        }
      })();
    },
    [billing],
  );

  const handleChangePlan = React.useCallback(
    (planKey: string) => {
      void billing.changePlan(planKey).catch(() => undefined);
    },
    [billing],
  );

  const handleCancel = React.useCallback(() => {
    void billing.cancel().catch(() => undefined);
  }, [billing]);

  return (
    <main className="min-h-dvh">
      <AppTopBar
        extra={
          canManage ? (
            <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex">
              <Link href="/settings/billing">
                <Settings className="size-4" aria-hidden /> Manage plan
              </Link>
            </Button>
          ) : null
        }
      />

      <section className="container py-10">
        <div className="mx-auto max-w-5xl space-y-6">
          <CreemReturnNotice />
          <PersonalPlans />
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
                <CreditCard className="size-7 text-primary" aria-hidden />
                Workspace plan
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Monthly or yearly subscription for a team workspace: a monthly
                credit allotment, seats and plan features, plus usage and
                invoices. Just need credits for yourself?{" "}
                <Link href="/wallet/plans" className="font-medium text-primary underline underline-offset-4">
                  Buy a one-time credit pack
                </Link>
                .
              </p>
            </div>
            <div className="flex items-center gap-3">
              {workspaces.length > 1 && (
                <WorkspacePicker
                  workspaces={workspaces}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  disabled={billing.status === "loading"}
                />
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => billing.reload()}
                disabled={billing.status === "loading" || !selectedId}
              >
                <RefreshCw
                  className={
                    billing.status === "loading"
                      ? "size-4 animate-spin"
                      : "size-4"
                  }
                  aria-hidden
                />
                Refresh
              </Button>
            </div>
          </div>

          {wsStatus === "error" ? (
            <Card>
              <CardContent className="py-8 text-sm text-destructive" role="alert">
                {wsError}
              </CardContent>
            </Card>
          ) : wsStatus === "ready" && workspaces.length === 0 ? (
            <EmptyWorkspaces />
          ) : wsStatus === "loading" ||
            billing.status === "loading" ||
            billing.status === "idle" ||
            perms.status === "loading" ? (
            <BillingSkeleton />
          ) : billing.status === "error" ? (
            <ErrorPanel message={billing.errorMessage} onRetry={billing.reload} />
          ) : (
            <div className="space-y-6">
              {billing.actionError && (
                <Card className="border-destructive/40 bg-destructive/5">
                  <CardContent className="flex items-start gap-3 py-4 text-sm text-destructive">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                    {billing.actionError}
                  </CardContent>
                </Card>
              )}

              <CurrentPlanCard
                subscription={billing.subscription}
                canManage={canManage}
                pending={billing.pending}
                onCancel={handleCancel}
              />

              <div className="grid gap-6 lg:grid-cols-2">
                <UsageMeters usage={billing.usage} period={billing.period} />
                <EntitlementsCard entitlements={billing.entitlements} />
              </div>

              <div>
                <h2 className="mb-3 text-lg font-semibold tracking-tight">
                  Plans
                </h2>
                {!hasSubscription && (
                  <LaunchGateNotice
                    gate={launch.gate.checkout}
                    className="mb-4"
                    meanwhile="Your workspace keeps its free plan and credits in the meantime."
                  />
                )}
                <PlanGrid
                  currentPlanKey={currentPlanKey}
                  hasSubscription={hasSubscription}
                  checkoutClosedReason={checkoutClosedReason}
                  canManage={canManage}
                  pending={billing.pending}
                  onSubscribe={handleSubscribe}
                  onChangePlan={handleChangePlan}
                />
              </div>

              <InvoicesCard invoices={billing.invoices} canManage={canManage} />
            </div>
          )}
          <BillingHelp className="mt-8 rounded-lg border border-border p-4 text-sm text-muted-foreground" />
        </div>
      </section>
    </main>
  );
}

function EmptyWorkspaces() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-2 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
          <CreditCard className="size-6 text-primary" aria-hidden />
        </span>
        <p className="font-medium">No workspaces yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Workspace plans belong to a team workspace. Create one (it takes a
          name), then come back here to pick a plan.
        </p>
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          <Button asChild size="sm">
            <Link href="/workspace">
              <Plus className="size-4" aria-hidden /> Create a workspace
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href="/wallet/plans">Buy credits for yourself</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function BillingSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-40 w-full rounded-lg" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-64 w-full rounded-lg" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-72 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">Couldn&apos;t load billing</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </CardContent>
    </Card>
  );
}
