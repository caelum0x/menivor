"use client";

import * as React from "react";
import { AlertCircle, Loader2, RefreshCw, ShoppingCart } from "lucide-react";
import { ApiError, createCheckout } from "@/lib/api";
import type { PaymentProvider } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { usePaymentProviders } from "@/lib/use-payment-providers";
import { ProviderToggle } from "@/components/marketing/ProviderToggle";
import { PRICING_PLANS } from "@/components/marketing/plans";
import {
  fetchPublicPackCatalog,
  mergeLiveCatalog,
} from "@/components/marketing/live-plans";
import type { PricingPlan } from "@/components/marketing/PricingCard";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Rails that carry the workspace id through checkout (iyzico cannot). */
const WORKSPACE_PROVIDERS: ReadonlySet<PaymentProvider> = new Set([
  "dodo",
  "stripe",
  "creem",
  "polar",
]);

interface BuyTeamCreditsProps {
  /** Workspace whose SHARED pool the purchased pack tops up. */
  workspaceId: string;
}

/** A purchasable pack: a pricing plan sold through hosted checkout. */
interface PurchasablePack {
  readonly planKey: string;
  readonly name: string;
  readonly credits: number;
  readonly price: string;
}

/**
 * The checkout-eligible packs (Free has no `planKey`), narrowed to the fields
 * this picker needs. Copy stays sourced from the shared pricing plans; price
 * and credits are overlaid from the live `GET /billing/plans` catalog.
 */
function toPacks(plans: readonly PricingPlan[]): readonly PurchasablePack[] {
  return plans.flatMap((plan) =>
    plan.planKey
      ? [
          {
            planKey: plan.planKey,
            name: plan.name,
            credits: plan.credits,
            price: plan.price,
          },
        ]
      : [],
  );
}

const DEFAULT_PACKS = toPacks(PRICING_PLANS);

/**
 * Admin/owner-only control to buy a credit pack for the workspace SHARED pool.
 * Mirrors the personal pricing flow: pick a pack, POST /billing/checkout with
 * this `workspaceId`, then redirect to the returned hosted checkout URL. Only
 * rendered when the caller can manage the workspace; surfaces loading + error
 * states inline. Purchases are fulfilled to the pool idempotently server-side.
 */
export function BuyTeamCredits({
  workspaceId,
}: Readonly<BuyTeamCreditsProps>) {
  const getApiToken = useApiToken();
  const {
    status: providersStatus,
    providers: enabledProviders,
    reload: reloadProviders,
  } = usePaymentProviders();
  const [packs, setPacks] = React.useState<readonly PurchasablePack[]>(DEFAULT_PACKS);
  const firstPack = DEFAULT_PACKS[0];
  const [planKey, setPlanKey] = React.useState<string>(
    firstPack ? firstPack.planKey : "",
  );
  const [provider, setProvider] = React.useState<PaymentProvider | null>(null);
  const [pending, setPending] = React.useState(false);
  const [errorMessage, setErrorMessage] = React.useState("");

  // Live pack prices/credits (display defaults stay if the catalog is down;
  // the server prices the checkout regardless).
  React.useEffect(() => {
    let active = true;
    void fetchPublicPackCatalog()
      .then((catalog) => {
        if (active) setPacks(toPacks(mergeLiveCatalog(PRICING_PLANS, catalog)));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  // Keep the chosen pack valid if the live catalog retired it.
  React.useEffect(() => {
    setPlanKey((current) =>
      packs.some((pack) => pack.planKey === current)
        ? current
        : (packs[0]?.planKey ?? ""),
    );
  }, [packs]);

  // Offer only enabled rails that can fund a workspace pool; fail closed when
  // the probe fails (retry below) instead of offering unconfigured rails.
  const availableProviders = React.useMemo<readonly PaymentProvider[]>(
    () =>
      providersStatus === "ready"
        ? enabledProviders.filter((p) => WORKSPACE_PROVIDERS.has(p))
        : [],
    [providersStatus, enabledProviders],
  );

  // Keep the selected provider within the available set.
  React.useEffect(() => {
    const [firstProvider] = availableProviders;
    setProvider((current) =>
      current && availableProviders.includes(current)
        ? current
        : (firstProvider ?? null),
    );
  }, [availableProviders]);

  const handleBuy = React.useCallback(async (): Promise<void> => {
    if (!planKey || pending || !provider) return;
    setPending(true);
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const { checkout_url } = await createCheckout(
        { plan_key: planKey, provider, workspace_id: workspaceId },
        { token },
      );
      if (!checkout_url) {
        throw new Error("Checkout did not return a redirect URL.");
      }
      // Hand off to the selected provider's hosted checkout page.
      window.location.assign(checkout_url);
    } catch (err) {
      setPending(false);
      setErrorMessage(resolveCheckoutError(err));
    }
  }, [getApiToken, pending, planKey, provider, workspaceId]);

  if (packs.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-secondary/30 p-4">
      <h4 className="flex items-center gap-2 text-sm font-medium">
        <ShoppingCart className="size-4 text-primary" aria-hidden />
        Buy team credits
      </h4>
      <p className="mt-1 text-xs text-muted-foreground">
        Purchase a pack for the shared pool. You&apos;ll be redirected to the
        selected provider&apos;s secure checkout.
      </p>

      <div className="mt-3 grid gap-1.5">
        <Label>Pay with</Label>
        {providersStatus === "loading" ? (
          <Skeleton className="h-9 w-48 rounded-lg" />
        ) : availableProviders.length > 0 && provider ? (
          <ProviderToggle
            value={provider}
            providers={availableProviders}
            onChange={setProvider}
            disabled={pending}
          />
        ) : providersStatus === "error" ? null : (
          <p className="text-xs text-muted-foreground">
            No payment methods are available right now.
          </p>
        )}
        {providersStatus === "error" && (
          <button
            type="button"
            onClick={reloadProviders}
            className="inline-flex w-fit items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <RefreshCw className="size-3" aria-hidden /> Couldn&apos;t load
            payment options. Retry
          </button>
        )}
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        <div className="grid gap-1.5">
          <Label htmlFor="buy-team-pack">Pack</Label>
          <Select
            id="buy-team-pack"
            value={planKey}
            disabled={pending}
            onChange={(e) => setPlanKey(e.target.value)}
          >
            {packs.map((pack) => (
              <option key={pack.planKey} value={pack.planKey}>
                {pack.name} — {pack.credits} credits ({pack.price})
              </option>
            ))}
          </Select>
        </div>
        <Button
          type="button"
          onClick={() => void handleBuy()}
          disabled={pending || !planKey || !provider}
          aria-busy={pending}
        >
          {pending ? (
            <>
              <Loader2 className="animate-spin" aria-hidden />
              Redirecting…
            </>
          ) : (
            <>
              <ShoppingCart aria-hidden />
              Buy
            </>
          )}
        </Button>
      </div>

      {errorMessage && (
        <p
          role="alert"
          className="mt-2 flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {errorMessage}
        </p>
      )}
    </div>
  );
}

/** Maps a thrown checkout error to a friendly, actionable message. */
function resolveCheckoutError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) {
      return "You need admin access to buy credits for this workspace.";
    }
    return friendlyErrorMessage(err);
  }
  if (err instanceof Error) return friendlyErrorMessage(err);
  return "Couldn't start checkout. Please try again.";
}
