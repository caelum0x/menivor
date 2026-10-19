"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, CreditCard, Loader2, RefreshCw } from "lucide-react";
import { ApiError, redeemReferral } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  accessErrorMessage,
  signUpHref,
  startCardCheck,
  useCreemReturn,
  useWebAccess,
  type CardCheckStatus,
} from "@/src/shared/access";
import { clearPendingReferral, readPendingReferral } from "./referral-capture";
import { MenivorMark } from "@/components/brand/MenivorMark";
import { providerLabel } from "@/src/shared/payments/mode";

/** Re-check a pending payment every 10 s for about 2 minutes. */
const PENDING_CHECK_MS = 10_000;
const PENDING_MAX_CHECKS = 12;

/**
 * Post-sign-up step, one screen: unlock the free reels with a $1 card check
 * (the active payment provider, Dodo Payments), then continue to `next` (the
 * create box, usually with the link the visitor already pasted) automatically.
 * Returning from checkout confirms the payment here and continues without
 * another click. Accounts that are already unlocked (or every account while
 * payments are paused) pass straight through.
 */
export function OnboardingFlow({ next }: Readonly<{ next: string }>) {
  const router = useRouter();
  const access = useWebAccess();
  const payment = useCreemReturn();
  useReferralRedemption(access.getToken, access.state.status === "ready" || access.state.status === "locked");

  const { refresh } = access;
  React.useEffect(() => {
    if (payment.phase === "done") refresh();
    if (payment.phase !== "pending") return;
    // The webhook settles a processing payment shortly. Keep re-checking for a
    // couple of minutes (not just once) so a slow webhook never strands someone
    // who already paid on the pay screen; "ready" then moves them on by itself.
    let checks = 0;
    const timer = setInterval(() => {
      checks += 1;
      refresh();
      if (checks >= PENDING_MAX_CHECKS) clearInterval(timer);
    }, PENDING_CHECK_MS);
    return () => clearInterval(timer);
  }, [payment.phase, refresh]);

  const { state } = access;
  const confirming = payment.phase === "confirming";

  React.useEffect(() => {
    if (confirming) return;
    if (state.status === "ready") router.replace(next);
    if (state.status === "signed-out") {
      router.replace(signUpHref(`/onboarding?next=${encodeURIComponent(next)}`));
    }
  }, [confirming, next, router, state.status]);

  return (
    <main className="min-h-dvh">
      <header className="glass-bar sticky top-0 z-40 border-b">
        <div className="container flex items-center py-4">
          <span className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </span>
        </div>
      </header>

      <section className="container max-w-xl space-y-6 py-12">
        {payment.phase === "pending" && (
          <p role="status" className="flex items-start gap-2 text-sm text-muted-foreground">
            <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" aria-hidden />
            {payment.message}
          </p>
        )}
        {payment.phase === "failed" && (
          <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {payment.message}
          </p>
        )}

        {confirming || state.status === "loading" || state.status === "signed-out" ? (
          <Status label={confirming ? "Confirming your payment…" : "Getting your account ready…"} />
        ) : state.status === "ready" ? (
          <Status
            done
            label={
              payment.phase === "done"
                ? `Payment confirmed. You have ${payment.result.balance} reel credits. Opening the create box…`
                : "Your account is ready. Opening the create box…"
            }
          />
        ) : state.status === "error" ? (
          <Card className="border-destructive/40 bg-destructive/5">
            <CardContent className="flex flex-col items-start gap-4 p-6">
              <p className="flex items-start gap-2 text-sm text-destructive">
                <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                {state.message}
              </p>
              <Button type="button" variant="outline" size="sm" onClick={access.refresh}>
                <RefreshCw className="size-4" aria-hidden /> Try again
              </Button>
            </CardContent>
          </Card>
        ) : (
          <UnlockCard
            card={state.card}
            next={next}
            getToken={access.getToken}
            awaitingPayment={payment.phase === "pending"}
            onCheckAgain={refresh}
          />
        )}
      </section>
    </main>
  );
}

function Status({ label, done = false }: Readonly<{ label: string; done?: boolean }>) {
  return (
    <p className="flex items-center gap-2 py-10 text-base text-muted-foreground" role="status">
      {done ? (
        <CheckCircle2 className="size-5 text-success" aria-hidden />
      ) : (
        <Loader2 className="size-5 animate-spin" aria-hidden />
      )}
      {label}
    </p>
  );
}

function UnlockCard({
  card,
  next,
  getToken,
  awaitingPayment = false,
  onCheckAgain,
}: Readonly<{
  card: CardCheckStatus;
  next: string;
  getToken: () => Promise<string | undefined>;
  /** The visitor already paid and the provider has not confirmed yet. */
  awaitingPayment?: boolean;
  onCheckAgain?: () => void;
}>) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const total = card.free_credits + card.card_check_credits;
  const price = `$${card.price_usd.toFixed(0)}`;

  const pay = async () => {
    setError("");
    setBusy(true);
    try {
      const token = await getToken();
      const { checkout_url: url } = await startCardCheck(next, { token });
      window.location.assign(url);
    } catch (err) {
      setError(accessErrorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-muted-foreground">Last step</p>
        <h1 className="text-3xl font-bold tracking-tight">Unlock your {card.free_credits} free reels</h1>
        <p className="mt-3 text-muted-foreground">
          Verify your card with a one-time {price} payment. The {price} is added to your
          balance as {card.card_check_credits} reel credit, so you start with {total} reels.
          No subscription, nothing else is charged.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4 p-6">
          {awaitingPayment ? (
            // Already paid: never offer a second payment while the provider confirms.
            <Button type="button" size="lg" variant="outline" onClick={onCheckAgain}>
              <RefreshCw className="size-4" aria-hidden /> Check my payment now
            </Button>
          ) : (
            <Button type="button" size="lg" onClick={() => void pay()} disabled={busy || !card.available}>
              {busy ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <CreditCard className="size-4" aria-hidden />
              )}
              {busy ? "Opening secure checkout…" : `Pay ${price} and unlock ${total} reels`}
            </Button>
          )}
          <p className="text-xs text-muted-foreground">
            Paid securely through {providerLabel(card.provider ?? "dodo")}, our payment provider. After
            paying you come straight back here and your first reels start from what you entered.
          </p>
          {!card.available && (
            <p role="status" className="text-sm text-muted-foreground">
              Card payments are being switched on right now. Refresh this page in a few minutes,
              or email support@menivor.com and we will unlock your account by hand.
            </p>
          )}
          {error && (
            <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
              <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
              {error}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Redeem a referral captured on /sign-up?ref=CODE exactly once, silently. */
function useReferralRedemption(getToken: () => Promise<string | undefined>, signedIn: boolean) {
  React.useEffect(() => {
    if (!signedIn) return;
    const code = readPendingReferral();
    if (!code) return;
    void (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        await redeemReferral(code, { token });
        clearPendingReferral();
      } catch (err) {
        // Invalid / self / already-used codes are dropped; transient errors retry next visit.
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) clearPendingReferral();
      }
    })();
  }, [getToken, signedIn]);
}
