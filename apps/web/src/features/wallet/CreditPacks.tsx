"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Check,
  Coins,
  ExternalLink,
  RefreshCw,
  Wallet,
} from "lucide-react";

import {
  createCheckout,
  getMe,
  getProviders,
  listPlans,
} from "@/lib/api";
import type {
  CheckoutRequest,
  Me,
  PaymentProvider,
  Plan,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { saveCheckoutIntent } from "@/lib/checkout-intent";
import { useSignedInState } from "@/lib/auth-state";
import { signInHref, signUpHref } from "@/lib/auth-redirect";
import { UserButton } from "@/components/auth/clerk-safe";
import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import { formatCents } from "@/components/billing/format";
import { WalletNav } from "@/components/wallet/WalletNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { getBalance, formatUsdMicros, type WalletBalance } from "./api";
import { fetchLaunchGate, readableApiError, type LaunchGate } from "@/src/shared/launch-gate";

type LoadState = "loading" | "ready" | "error";

/** Friendly label per known provider; unknown codes are title-cased. */
const PROVIDER_LABELS: Record<PaymentProvider, string> = {
  stripe: "Stripe",
  iyzico: "iyzico (Turkey)",
  creem: "Creem",
  polar: "Polar",
  dodo: "Dodo Payments",
  paddle: "Paddle",
};

function providerLabel(provider: PaymentProvider): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

/** Display price for a pack from whichever pricing shape the backend supplies. */
function planPrice(plan: Readonly<Plan>): string {
  if (plan.price && plan.price.trim()) return plan.price;
  if (typeof plan.amount === "number" && Number.isFinite(plan.amount)) {
    return formatCents(plan.amount, plan.currency);
  }
  return "—";
}

/**
 * Personal wallet credit packs — buy one-off render credit for the caller's OWN
 * balance (distinct from the workspace subscription at /billing). Loads the live
 * balance, the caller's credit count, the purchasable packs (GET /billing/plans)
 * and the ENABLED payment providers (GET /billing/providers), then starts a
 * hosted checkout (POST /billing/checkout) behind an explicit confirmation. No
 * credit is granted here — the verified payment webhook fulfils the pack, so the
 * page tells the buyer to refresh the wallet once payment completes.
 */
export function CreditPacks() {
  const getToken = useApiToken();
  const { isLoaded: authLoaded, isSignedIn } = useSignedInState();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = React.useState("");
  const [balance, setBalance] = React.useState<WalletBalance | null>(null);
  const [me, setMe] = React.useState<Me | null>(null);
  const [plans, setPlans] = React.useState<Plan[]>([]);
  const [providers, setProviders] = React.useState<PaymentProvider[]>([]);
  const [provider, setProvider] = React.useState<PaymentProvider | "">("");
  const [launch, setLaunch] = React.useState<LaunchGate | null>(null);
  const [confirmKey, setConfirmKey] = React.useState<string | null>(null);
  const [checkoutKey, setCheckoutKey] = React.useState<string | null>(null);
  const [checkoutError, setCheckoutError] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getToken();
      const [balanceResult, meResult, plansResult, providersResult, launchResult] =
        await Promise.all([
          getBalance({ token }),
          getMe({ token }),
          listPlans({ token }),
          getProviders({ token }),
          // Launch gates are advisory UX (the API enforces them anyway):
          // when the status route itself fails, leave checkout ungated. Read
          // as the caller so pilot staff see their checkout override.
          fetchLaunchGate(token ?? undefined).catch(() => null),
        ]);
      setBalance(balanceResult);
      setMe(meResult);
      setPlans(plansResult);
      setProviders(providersResult);
      setLaunch(launchResult);
      setProvider((current) =>
        current && providersResult.includes(current)
          ? current
          : (providersResult[0] ?? ""),
      );
      setStatus("ready");
    } catch (err) {
      setErrorMessage(readableApiError(err, "Something went wrong loading credit packs."));
      setStatus("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const startCheckout = React.useCallback(
    async (planKey: string) => {
      if (!provider) return;
      setCheckoutError("");
      setCheckoutKey(planKey);
      try {
        const token = await getToken();
        if (!token) {
          // Paid credit must land on a real account, never a browser-only
          // guest session that is lost when storage is cleared.
          setCheckoutError("Sign in to buy credit packs.");
          return;
        }
        const body: CheckoutRequest = { plan_key: planKey, provider };
        const result = await createCheckout(body, { token });
        if (result.checkout_url && typeof window !== "undefined") {
          saveCheckoutIntent({
            kind: "pack",
            planKey,
            baselineCredits: me?.credits ?? null,
          });
          window.location.assign(result.checkout_url);
          return;
        }
        setCheckoutError(
          "Checkout did not return a payment link. Please try again.",
        );
      } catch (err) {
        setCheckoutError(readableApiError(err, "Could not start checkout. Please try again."));
      } finally {
        setCheckoutKey(null);
        setConfirmKey(null);
      }
    },
    [getToken, me, provider],
  );

  // Server-owned launch gate: while `features.checkout` is false the API
  // rejects POST /billing/checkout, so present "opens soon" instead of a
  // dead purchase button. Fail-open when the status could not be read.
  const checkoutOpen = launch === null || launch.checkout.open;
  const needsAccount = authLoaded && !isSignedIn;

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Coins className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Credit packs</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={
                status === "loading" ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"
              }
              aria-hidden
            />
            Refresh
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <WalletNav />

      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">
        Top up your personal wallet with a one-off credit pack. Credit is added
        to your balance once payment completes — this is separate from a
        workspace subscription.
      </p>

      {status === "loading" && <CreditPacksSkeleton />}

      {status === "error" && (
        <ErrorPanel message={errorMessage} onRetry={() => void load()} />
      )}

      {status === "ready" && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <SummaryCard
              label="Wallet balance"
              value={
                balance ? formatUsdMicros(balance.available_micros) : "—"
              }
              hint={balance?.plan ? `${balance.plan} plan` : undefined}
            />
            <SummaryCard
              label="Render credits"
              value={(me?.credits ?? 0).toLocaleString("en-US")}
            />
            <SummaryCard
              label="Reserved (in-flight)"
              value={balance ? formatUsdMicros(balance.reserved_micros) : "—"}
            />
          </div>

          {!checkoutOpen && (
            <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-4">
              <div>
                <p className="text-sm font-medium">
                  Purchases have not opened yet
                </p>
                <p className="text-sm text-muted-foreground">
                  Paid credit packs are not on sale yet. Leave your email and
                  we will tell you the moment checkout opens.
                </p>
              </div>
              <WaitlistForm
                source="wallet-plans-checkout-gate"
                submitLabel="Notify me"
                successMessage="Thanks. We'll email you when paid packs open."
              />
            </div>
          )}

          {checkoutOpen && needsAccount && (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-primary/40 bg-primary/5 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-medium">
                  Create an account to buy credit packs
                </p>
                <p className="text-sm text-muted-foreground">
                  You&apos;re using a guest session saved only in this browser.
                  Paid credit goes to a real account so it can&apos;t be lost —
                  your guest reels and credits move over when you sign up.
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button asChild size="sm">
                  <Link href={signUpHref("/wallet/plans")}>Create account</Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href={signInHref("/wallet/plans")}>Sign in</Link>
                </Button>
              </div>
            </div>
          )}

          {checkoutOpen && !needsAccount && (
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid gap-1">
              <Label htmlFor="credit-provider">Payment method</Label>
              <Select
                id="credit-provider"
                className="w-56"
                value={provider}
                disabled={providers.length === 0}
                onChange={(event) =>
                  setProvider(event.target.value as PaymentProvider)
                }
              >
                {providers.length === 0 ? (
                  <option value="">No payment method available</option>
                ) : (
                  providers.map((p) => (
                    <option key={p} value={p}>
                      {providerLabel(p)}
                    </option>
                  ))
                )}
              </Select>
            </div>
            {providers.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Checkout is not currently available. Please check back soon.
              </p>
            )}
          </div>
          )}

          {checkoutError && (
            <p className="text-sm text-destructive" role="alert">
              {checkoutError}
            </p>
          )}

          {plans.length === 0 ? (
            <EmptyPacks />
          ) : (
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {plans.map((plan) => {
                const key = plan.plan_key;
                const isConfirming = confirmKey === key;
                const isBusy = checkoutKey === key;
                const disabled =
                  !checkoutOpen ||
                  needsAccount ||
                  providers.length === 0 ||
                  !provider ||
                  checkoutKey !== null;
                return (
                  <li key={key}>
                    <Card className="flex h-full flex-col">
                      <CardContent className="flex flex-1 flex-col gap-3 p-5">
                        <div className="flex items-start justify-between gap-2">
                          <h2 className="font-semibold">
                            {plan.name ?? key}
                          </h2>
                          {typeof plan.credits === "number" && (
                            <Badge variant="secondary" className="shrink-0">
                              {plan.credits.toLocaleString("en-US")} credits
                            </Badge>
                          )}
                        </div>
                        <p className="text-3xl font-bold tracking-tight tabular-nums">
                          {planPrice(plan)}
                        </p>
                        <div className="mt-auto">
                          {isConfirming ? (
                            <div className="flex items-center gap-2">
                              <Button
                                size="sm"
                                className="flex-1"
                                disabled={isBusy}
                                onClick={() => void startCheckout(key)}
                              >
                                {isBusy ? "Starting…" : "Confirm"}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={isBusy}
                                onClick={() => setConfirmKey(null)}
                              >
                                Cancel
                              </Button>
                            </div>
                          ) : (
                            <Button
                              size="sm"
                              variant="outline"
                              className="w-full"
                              disabled={disabled}
                              onClick={() => {
                                setCheckoutError("");
                                setConfirmKey(key);
                              }}
                            >
                              Buy pack
                            </Button>
                          )}
                          {isConfirming && provider && (
                            <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                              <ExternalLink className="h-3 w-3" aria-hidden />
                              Continues to {providerLabel(provider)} checkout.
                            </p>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  </li>
                );
              })}
            </ul>
          )}

          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Check className="h-3.5 w-3.5" aria-hidden />
            Credit is granted after payment settles. Return to the{" "}
            <Link href="/wallet" className="underline">
              wallet
            </Link>{" "}
            and refresh to see your new balance.
          </p>
        </div>
      )}
    </main>
  );
}

function SummaryCard({
  label,
  value,
  hint,
}: Readonly<{ label: string; value: string; hint?: string }>) {
  return (
    <Card>
      <CardContent className="py-5">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        {hint && (
          <p className="mt-1 text-xs uppercase tracking-wide text-muted-foreground">
            {hint}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyPacks() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-2 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
          <Wallet className="size-6 text-primary" aria-hidden />
        </span>
        <p className="font-medium">No credit packs available</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          There are no purchasable packs right now. You can still add a custom
          amount from the wallet overview.
        </p>
        <Button asChild variant="outline" size="sm" className="mt-2">
          <Link href="/wallet">Go to wallet</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function CreditPacksSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-10 w-56 rounded-md" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-40 w-full rounded-lg" />
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
            <p className="font-medium">Couldn&apos;t load credit packs</p>
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
