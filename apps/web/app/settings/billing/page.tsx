"use client";

import * as React from "react";
import Link from "next/link";
import { CreditCard } from "lucide-react";
import { saveCheckoutIntent } from "@/lib/checkout-intent";
import type { SubscribeRequest } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { CurrentPlanCard } from "@/components/billing/CurrentPlanCard";
import { PlanGrid } from "@/components/billing/PlanGrid";
import { UsageMeters } from "@/components/billing/UsageMeters";
import { InvoicesCard } from "@/components/billing/InvoicesCard";
import { BillingHelp } from "@/components/billing/BillingHelp";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { useWorkspacePermissions } from "@/lib/use-workspace-permissions";
import { useWorkspaceBilling } from "@/lib/use-workspace-billing";
import { LaunchGateNotice, useLaunchGate } from "@/src/shared/launch-gate";

/**
 * ENTERPRISE — Plan management (settings/billing). The manager-facing billing
 * surface: change or cancel the workspace subscription, review usage against the
 * plan, and pull invoices. Every control requires `billing.manage`; a caller
 * without it sees a clear "not authorized" state rather than another tenant's
 * data. Tenant-isolated — only the selected workspace's billing is ever shown,
 * and the server re-checks the gate on every mutation.
 */
export default function BillingSettingsPage() {
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
    (planKey: string) => void billing.changePlan(planKey).catch(() => undefined),
    [billing],
  );
  const handleCancel = React.useCallback(
    () => void billing.cancel().catch(() => undefined),
    [billing],
  );

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/billing" />

      <section className="container py-10">
        <div className="mx-auto max-w-3xl space-y-6">
          <div>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <CreditCard className="size-7 text-primary" aria-hidden />
              Plan &amp; billing
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Change or cancel this workspace&apos;s subscription, review usage,
              and download invoices. Only billing admins and owners can manage
              plans.
            </p>
          </div>

          {wsStatus === "error" ? (
            <Card>
              <CardContent className="py-8 text-sm text-destructive" role="alert">
                {wsError}
              </CardContent>
            </Card>
          ) : wsStatus === "ready" && workspaces.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="flex flex-col items-center gap-2 py-16 text-center">
                <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
                  <CreditCard className="size-6 text-primary" aria-hidden />
                </span>
                <p className="font-medium">No workspaces yet</p>
                <p className="text-sm text-muted-foreground">
                  Create a workspace to manage its subscription and billing.
                </p>
              </CardContent>
            </Card>
          ) : (
            <>
              {workspaces.length > 1 && (
                <Card>
                  <CardContent className="py-4">
                    <WorkspacePicker
                      workspaces={workspaces}
                      selectedId={selectedId}
                      onSelect={setSelectedId}
                      disabled={billing.status === "loading"}
                    />
                  </CardContent>
                </Card>
              )}

              {perms.status === "ready" && !canManage ? (
                <Card>
                  <CardContent className="space-y-2 py-8 text-sm text-muted-foreground">
                    <p>
                      You need the workspace <strong>billing</strong>,{" "}
                      <strong>admin</strong>, or <strong>owner</strong> role to
                      manage plans and invoices. Ask a billing admin for access.
                    </p>
                    <p>
                      You can still view your plan usage on the{" "}
                      <Link href="/billing" className="text-primary hover:underline">
                        billing overview
                      </Link>
                      .
                    </p>
                  </CardContent>
                </Card>
              ) : canManage ? (
                <div className="space-y-6">
                  {billing.actionError && (
                    <Card className="border-destructive/40 bg-destructive/5">
                      <CardContent className="py-4 text-sm text-destructive">
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

                  <div>
                    <h2 className="mb-3 text-lg font-semibold tracking-tight">
                      Change plan
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

                  <div className="flex flex-col gap-1.5 sm:max-w-xs">
                    <Label htmlFor="usage-period">Usage month</Label>
                    <Input
                      id="usage-period"
                      type="month"
                      value={billing.period}
                      onChange={(e) =>
                        billing.setPeriod(e.target.value || billing.period)
                      }
                    />
                  </div>
                  <UsageMeters usage={billing.usage} period={billing.period} />

                  <InvoicesCard
                    invoices={billing.invoices}
                    canManage={canManage}
                  />
                </div>
              ) : (
                <Card>
                  <CardContent className="py-8 text-sm text-muted-foreground">
                    Loading workspace permissions…
                  </CardContent>
                </Card>
              )}
            </>
          )}
          <BillingHelp className="mt-8 rounded-lg border border-border p-4 text-sm text-muted-foreground" />
        </div>
      </section>
    </main>
  );
}
