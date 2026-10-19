"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, RefreshCw, UserRound, Users } from "lucide-react";
import { ApiError, createCheckout, getLaunchStatus, getMe } from "@/lib/api";
import { saveCheckoutIntent } from "@/lib/checkout-intent";
import type { PaymentProvider } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { useSignedInState } from "@/lib/auth-state";
import { signInHref, signUpHref } from "@/lib/auth-redirect";
import { usePaymentProviders } from "@/lib/use-payment-providers";
import { Skeleton } from "@/components/ui/skeleton";
import { PricingCard, type PricingPlan } from "@/components/marketing/PricingCard";
import { ProviderToggle } from "@/components/marketing/ProviderToggle";
import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import {
  fetchPublicPackCatalog,
  mergeLiveCatalog,
} from "@/components/marketing/live-plans";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** On-page anchor for the launch waitlist shown while checkout is gated. */
const LAUNCH_WAITLIST_ID = "launch-waitlist";
/** Where buyers return after signing in / signing up from a pack CTA. */
const PRICING_PATH = "/pricing";

interface CheckoutPlansProps {
  readonly plans: readonly PricingPlan[];
}

/**
 * Client-side pricing grid with a provider toggle (Dodo Payments, Stripe, iyzico, Creem, or
 * Polar) limited to the providers the backend has ENABLED (fail-closed: until
 * that list loads, no rail is offered). For plans carrying a
 * `planKey`, the CTA POSTs /billing/checkout with the chosen provider and
 * redirects the buyer to the returned hosted checkout URL. Plans without a
 * `planKey` (Free) fall back to their `ctaHref` link. Surfaces loading and
 * error states inline.
 */
export function CheckoutPlans({ plans }: CheckoutPlansProps) {
  const getToken = useApiToken();
  const { isLoaded: authLoaded, isSignedIn } = useSignedInState();
  const [livePlans, setLivePlans] = React.useState<readonly PricingPlan[]>(plans);
  const {
    status: providersStatus,
    providers: enabledProviders,
    reload: reloadProviders,
  } = usePaymentProviders();
  // No provider is assumed until the server says which rails are enabled.
  const [provider, setProvider] = React.useState<PaymentProvider | null>(null);
  const [pendingKey, setPendingKey] = React.useState<string | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string>("");
  // Server launch gate: while `features.checkout` is false the API rejects
  // POST /billing/checkout, so paid CTAs route to the waitlist instead of a
  // dead checkout call. Fail-open if the status probe itself fails.
  const [checkoutOpen, setCheckoutOpen] = React.useState(true);

  // Live pack catalog (price + credits per plan_key) from the backend.
  React.useEffect(() => {
    let active = true;
    void fetchPublicPackCatalog()
      .then((catalog) => {
        if (active) setLivePlans(mergeLiveCatalog(plans, catalog));
      })
      .catch(() => {
        // Keep the display defaults; the server still prices at checkout.
      });
    return () => {
      active = false;
    };
  }, [plans]);

  React.useEffect(() => {
    let active = true;
    void getLaunchStatus()
      .then((launch) => {
        if (active) setCheckoutOpen(launch.features.checkout !== false);
      })
      .catch(() => {
        // Unknown state: leave checkout reachable; the API still enforces.
      });
    return () => {
      active = false;
    };
  }, []);

  // Providers to offer the buyer: ONLY the server's enabled list. If the probe
  // fails we fail closed (offer a retry) rather than showing rails that may not
  // be configured and would error at checkout.
  const availableProviders = React.useMemo<readonly PaymentProvider[]>(
    () => (providersStatus === "ready" ? enabledProviders : []),
    [providersStatus, enabledProviders],
  );

  // Keep the selected provider valid: snap to the first available option
  // whenever the available set changes and no longer includes it.
  React.useEffect(() => {
    const [firstProvider] = availableProviders;
    setProvider((current) =>
      current && availableProviders.includes(current)
        ? current
        : (firstProvider ?? null),
    );
  }, [availableProviders]);

  const handleSelect = React.useCallback(
    async (plan: PricingPlan) => {
      if (!plan.planKey || pendingKey) return;
      if (!provider) {
        setErrorMessage(
          providersStatus === "error"
            ? "Couldn't load payment options. Retry above, then choose a pack."
            : "No payment method is available right now.",
        );
        return;
      }
      if (!isSignedIn) {
        // Credits must land on a real account, never a browser-only guest.
        window.location.assign(signUpHref(PRICING_PATH));
        return;
      }
      setPendingKey(plan.planKey);
      setErrorMessage("");
      try {
        const token = await getToken();
        if (!token) {
          throw new ApiError("Your session expired. Please sign in again.", 401);
        }
        const baseline = await getMe({ token }).catch(() => null);
        const { checkout_url } = await createCheckout(
          { plan_key: plan.planKey, provider },
          { token },
        );
        if (!checkout_url) {
          throw new Error("Checkout did not return a redirect URL.");
        }
        saveCheckoutIntent({
          kind: "pack",
          planKey: plan.planKey,
          baselineCredits: baseline?.credits ?? null,
        });
        // Hand off to the provider's hosted checkout page.
        window.location.assign(checkout_url);
      } catch (err) {
        setPendingKey(null);
        setErrorMessage(resolveCheckoutError(err));
      }
    },
    [getToken, isSignedIn, pendingKey, provider, providersStatus],
  );

  // Launch-gated presentation: paid packs stay visible with honest pricing,
  // but their CTA scrolls to the waitlist form below until checkout opens.
  // Signed-out visitors are asked to create an account first so paid credits
  // are never stranded on a browser-only guest session.
  const displayPlans = React.useMemo<readonly PricingPlan[]>(() => {
    if (!checkoutOpen) {
      return livePlans.map((plan) =>
        plan.planKey
          ? {
              ...plan,
              planKey: undefined,
              ctaLabel: "Opens at launch — get notified",
              ctaHref: `#${LAUNCH_WAITLIST_ID}`,
            }
          : plan,
      );
    }
    if (authLoaded && !isSignedIn) {
      return livePlans.map((plan) =>
        plan.planKey
          ? {
              ...plan,
              planKey: undefined,
              ctaLabel: "Create an account to buy",
              ctaHref: signUpHref(PRICING_PATH),
            }
          : plan,
      );
    }
    return livePlans;
  }, [authLoaded, checkoutOpen, isSignedIn, livePlans]);

  return (
    <div className="flex flex-col gap-8">
      {!checkoutOpen && (
        <p className="mx-auto max-w-xl text-center text-sm text-muted-foreground">
          Paid credit packs are not on sale yet. Leave your email below to
          hear the moment checkout opens.
        </p>
      )}
      {checkoutOpen && authLoaded && !isSignedIn && (
        <p className="mx-auto max-w-xl text-center text-sm text-muted-foreground">
          Credit packs are added to your Menivor account so they follow you to
          every device.{" "}
          <Link href={signInHref(PRICING_PATH)} className="font-medium text-primary underline underline-offset-4">
            Sign in
          </Link>{" "}
          or create a free account to buy.
        </p>
      )}
      {checkoutOpen && isSignedIn && (
      <div className="flex flex-col items-center gap-2">
        <span className="text-sm text-muted-foreground">Pay with</span>
        {providersStatus === "loading" ? (
          <Skeleton className="h-10 w-56 rounded-lg" />
        ) : availableProviders.length > 0 && provider ? (
          <ProviderToggle
            value={provider}
            providers={availableProviders}
            onChange={setProvider}
            disabled={pendingKey !== null}
          />
        ) : providersStatus === "error" ? null : (
          <p className="text-sm text-muted-foreground">
            No payment methods are available right now.
          </p>
        )}
        {providersStatus === "error" && (
          <button
            type="button"
            onClick={reloadProviders}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <RefreshCw className="size-3" aria-hidden /> Couldn&apos;t load
            payment options. Retry
          </button>
        )}
      </div>
      )}

      {errorMessage && (
        <div
          role="alert"
          className="mx-auto flex max-w-xl items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm"
        >
          <AlertTriangle
            className="mt-0.5 size-4 shrink-0 text-destructive"
            aria-hidden
          />
          <p className="text-muted-foreground">{errorMessage}</p>
        </div>
      )}

      <div className="mx-auto grid w-full max-w-5xl grid-cols-1 gap-6 md:grid-cols-3 md:items-stretch">
        {displayPlans.map((plan) => (
          <PricingCard
            key={plan.name}
            plan={plan}
            onSelect={plan.planKey ? handleSelect : undefined}
            pending={pendingKey === plan.planKey}
            disabled={pendingKey !== null && pendingKey !== plan.planKey}
          />
        ))}
      </div>

      {!checkoutOpen && (
        <div
          id={LAUNCH_WAITLIST_ID}
          className="glass-subtle mx-auto w-full max-w-xl scroll-mt-24 rounded-2xl p-6"
        >
          <p className="font-medium">Get notified when paid packs open</p>
          <p className="mt-1 text-sm text-muted-foreground">
            One email when checkout opens. No spam, unsubscribe any time.
          </p>
          <div className="mt-4">
            <WaitlistForm
              source="pricing-checkout-gate"
              submitLabel="Notify me"
              successMessage="Thanks. We'll email you when paid packs open."
            />
          </div>
        </div>
      )}

      <div className="glass-subtle mx-auto grid w-full max-w-5xl gap-4 rounded-2xl p-6 sm:grid-cols-2">
        <div className="flex items-start gap-3">
          <UserRound className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
          <div>
            <p className="font-medium">Credit packs (above)</p>
            <p className="text-sm text-muted-foreground">
              One-time purchase. Credits go to your personal balance — no
              subscription, nothing renews.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <Users className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
          <div>
            <p className="font-medium">Workspace plans</p>
            <p className="text-sm text-muted-foreground">
              Monthly or yearly subscription for teams: a monthly credit
              allotment, seats, API access and priority rendering.{" "}
              <Link href="/billing" className="font-medium text-primary underline underline-offset-4">
                Compare workspace plans
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Maps a thrown checkout error to a friendly, actionable message. */
function resolveCheckoutError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) {
      return "Please sign in to buy credits, then try again.";
    }
    return friendlyErrorMessage(err);
  }
  if (err instanceof Error) return friendlyErrorMessage(err);
  return "Couldn't start checkout. Please try again.";
}
