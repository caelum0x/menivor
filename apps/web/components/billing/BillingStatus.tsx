"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  CheckCircle2,
  Coins,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { ApiError, getMe } from "@/lib/api";
import type { Me } from "@/lib/types";
import {
  clearCheckoutIntent,
  readCheckoutIntent,
  type CheckoutIntent,
} from "@/lib/checkout-intent";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/** Webhook fulfilment is usually seconds; poll for up to ~90s. */
const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 30;

interface BillingStatusProps {
  readonly tone: "success" | "cancel";
  readonly title: string;
  readonly description: string;
}

type Fulfilment = "waiting" | "credited" | "timeout" | "untracked";

function fulfilmentFor(intent: CheckoutIntent | null, me: Me): Fulfilment {
  if (!intent || intent.kind !== "pack" || intent.baselineCredits === null) {
    return "untracked";
  }
  return me.credits > intent.baselineCredits ? "credited" : "waiting";
}

/**
 * Post-checkout status card for the success and cancel routes. On success it
 * knows (from the checkout intent saved before the redirect) whether a credit
 * pack or a workspace subscription was bought, and for packs it polls
 * GET /me until the webhook-granted credits land, instead of reading once.
 */
export function BillingStatus({ tone, title, description }: BillingStatusProps) {
  const { getToken, isLoaded } = useAuth();
  const isSuccess = tone === "success";
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [me, setMe] = React.useState<Me | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string>("");
  const [intent, setIntent] = React.useState<CheckoutIntent | null>(null);
  const [fulfilment, setFulfilment] = React.useState<Fulfilment>("untracked");

  React.useEffect(() => {
    setIntent(readCheckoutIntent());
    if (!isSuccess) clearCheckoutIntent();
  }, [isSuccess]);

  const fetchMe = React.useCallback(async (): Promise<Me | null> => {
    try {
      const token = (await getToken()) ?? undefined;
      const meResult = await getMe({ token });
      setMe(meResult);
      setStatus("ready");
      setErrorMessage("");
      return meResult;
    } catch (err) {
      setErrorMessage(
        friendlyErrorMessage(err, "Couldn't refresh your credit balance."),
      );
      setStatus("error");
      return null;
    }
  }, [getToken]);

  const refresh = React.useCallback(async () => {
    setStatus("loading");
    const result = await fetchMe();
    if (result && isSuccess) {
      const next = fulfilmentFor(readCheckoutIntent(), result);
      if (next === "credited") clearCheckoutIntent();
      setFulfilment((prev) => (next === "waiting" && prev === "timeout" ? "timeout" : next));
    }
  }, [fetchMe, isSuccess]);

  // Initial read + polling until credited (packs) or the poll budget runs out.
  React.useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;

    const tick = async () => {
      const result = await fetchMe();
      if (cancelled || !result || !isSuccess) return;
      const next = fulfilmentFor(readCheckoutIntent(), result);
      if (next === "credited") {
        clearCheckoutIntent();
        setFulfilment("credited");
        return;
      }
      if (next === "untracked") {
        setFulfilment("untracked");
        return;
      }
      polls += 1;
      if (polls >= MAX_POLLS) {
        setFulfilment("timeout");
        return;
      }
      setFulfilment("waiting");
      timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [fetchMe, isLoaded, isSuccess]);

  const isSubscription = isSuccess && intent?.kind === "subscription";
  const Icon = isSuccess ? CheckCircle2 : XCircle;
  const heading = isSubscription ? "Subscription started" : title;
  const body = isSubscription
    ? "Your workspace plan is being activated. Its monthly credits and plan details appear on the workspace billing page within a minute."
    : description;

  return (
    <Card className="mx-auto w-full max-w-md text-center">
      <CardContent className="flex flex-col items-center gap-5 p-8">
        <span
          className={cn(
            "flex size-14 items-center justify-center rounded-full",
            isSuccess ? "bg-success/10" : "bg-muted",
          )}
        >
          <Icon
            className={cn(
              "size-7",
              isSuccess ? "text-success" : "text-muted-foreground",
            )}
            aria-hidden
          />
        </span>

        <div>
          <h1 className="text-2xl font-bold tracking-tight">{heading}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{body}</p>
        </div>

        <div
          className="w-full rounded-lg border border-border bg-secondary/30 p-4"
          aria-live="polite"
        >
          <div className="flex items-center justify-center gap-2 text-sm">
            <Coins className="size-4 text-accent" aria-hidden />
            {status === "loading" && !me ? (
              <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
                Updating your balance…
              </span>
            ) : status === "error" ? (
              <span className="text-muted-foreground">{errorMessage}</span>
            ) : (
              <span className="text-muted-foreground">
                Personal balance:{" "}
                <span className="font-semibold text-foreground">
                  {me?.credits ?? 0}
                </span>{" "}
                credit{me?.credits === 1 ? "" : "s"}
              </span>
            )}
          </div>
          {isSuccess && intent?.kind === "pack" && (
            <p className="mt-2 text-xs text-muted-foreground">
              {fulfilment === "credited"
                ? "Your credit pack has been added."
                : fulfilment === "timeout"
                  ? "Payment received — credits can take a few minutes to post. Refresh in a moment, or contact support if they don't appear."
                  : fulfilment === "waiting"
                    ? "Waiting for the payment provider to confirm your pack…"
                    : null}
            </p>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={() => void refresh()}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={cn("size-3.5", status === "loading" && "animate-spin")}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        <div className="flex w-full flex-col gap-2 sm:flex-row">
          <Button asChild className="flex-1">
            <Link href={isSubscription ? "/billing" : "/reels"}>
              {isSubscription ? "View workspace plan" : "Go to my reels"}
            </Link>
          </Button>
          <Button asChild variant="outline" className="flex-1">
            <Link href={isSubscription ? "/reels" : "/wallet/plans"}>
              {isSubscription
                ? "Go to my reels"
                : isSuccess
                  ? "Buy more credits"
                  : "Back to credit packs"}
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
