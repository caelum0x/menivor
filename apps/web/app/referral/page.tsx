"use client";

import * as React from "react";
import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { AlertTriangle, Coins, RefreshCw } from "lucide-react";
import { ApiError, getMe, getReferral } from "@/lib/api";
import type { Me, Referral } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ReferralCard } from "@/components/referral/ReferralCard";
import { RedeemForm } from "@/components/referral/RedeemForm";
import { MenivorMark } from "@/components/brand/MenivorMark";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/** Builds the shareable invite URL for a code using the current browser origin. */
function buildShareUrl(origin: string, code: string): string {
  if (!origin || !code) return "";
  return `${origin}/sign-up?ref=${encodeURIComponent(code)}`;
}

export default function ReferralPage() {
  const getToken = useApiToken();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [referral, setReferral] = React.useState<Referral | null>(null);
  const [me, setMe] = React.useState<Me | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string>("");
  const [origin, setOrigin] = React.useState<string>("");

  // Resolve the origin on the client only (guards against SSR hydration drift).
  React.useEffect(() => {
    if (typeof window !== "undefined") setOrigin(window.location.origin);
  }, []);

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getToken();
      const [referralResult, meResult] = await Promise.all([
        getReferral({ token }),
        getMe({ token }),
      ]);
      setReferral(referralResult);
      setMe(meResult);
      setStatus("ready");
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Something went wrong loading your referral details.");
      setErrorMessage(message);
      setStatus("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Refresh only the credit balance after a successful redeem — the referral
  // stats card reflects the caller's own code, which redeeming does not change.
  const refreshCredits = React.useCallback(async () => {
    try {
      const token = await getToken();
      const meResult = await getMe({ token });
      setMe(meResult);
    } catch {
      // Non-fatal: the redeem already succeeded; the badge simply lags until
      // the next full load.
    }
  }, [getToken]);

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link
            href="/reels"
            className="flex items-center gap-2 font-semibold"
          >
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <CreditsBadge credits={me?.credits} loading={status === "loading"} />
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-12">
        <div className="mx-auto max-w-2xl">
          <div className="mb-8 text-center">
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Referrals
            </h1>
            <p className="mt-3 text-muted-foreground">
              Invite friends to Menivor and earn credits when they join.
            </p>
          </div>

          {status === "loading" && <ReferralSkeleton />}

          {status === "error" && (
            <ErrorPanel message={errorMessage} onRetry={() => void load()} />
          )}

          {status === "ready" && referral && (
            <div className="space-y-6">
              <ReferralCard
                referral={referral}
                shareUrl={buildShareUrl(origin, referral.code)}
              />
              <RedeemForm onRedeemed={() => void refreshCredits()} />
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function CreditsBadge({
  credits,
  loading,
}: Readonly<{ credits?: number; loading: boolean }>) {
  if (loading && credits === undefined) {
    return <Skeleton className="h-6 w-24 rounded-full" />;
  }
  return (
    <Badge variant="outline" className="gap-1.5 px-3 py-1" title="Available credits">
      <Coins className="size-3.5 text-accent" aria-hidden />
      <span className="font-medium">{credits ?? 0}</span>
      <span className="text-muted-foreground">credits</span>
    </Badge>
  );
}

function ReferralSkeleton() {
  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-4 p-6">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <div className="grid grid-cols-2 gap-3">
            <Skeleton className="h-20 w-full rounded-lg" />
            <Skeleton className="h-20 w-full rounded-lg" />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-4 p-6">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
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
            <p className="font-medium">Couldn&apos;t load your referral details</p>
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
