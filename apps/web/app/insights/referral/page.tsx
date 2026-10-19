"use client";

import * as React from "react";
import { AlertTriangle, Coins, Gift, RefreshCw } from "lucide-react";
import { ApiError, getMe, getReferral } from "@/lib/api";
import type { Me, Referral } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ReferralCard } from "@/components/referral/ReferralCard";
import { RedeemForm } from "@/components/referral/RedeemForm";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/** Builds the shareable invite URL for a code using the current browser origin. */
function buildShareUrl(origin: string, code: string): string {
  if (!origin || !code) return "";
  return `${origin}/sign-up?ref=${encodeURIComponent(code)}`;
}

/** Growth › Referrals — invite links, earned-credit stats, and redeeming. */
export default function InsightsReferralPage() {
  const getToken = useApiToken();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [referral, setReferral] = React.useState<Referral | null>(null);
  const [me, setMe] = React.useState<Me | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string>("");
  const [origin, setOrigin] = React.useState<string>("");

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

  // Refresh only the credit balance after a successful redeem — the caller's
  // own referral stats are unaffected by redeeming someone else's code.
  const refreshCredits = React.useCallback(async () => {
    try {
      const token = await getToken();
      setMe(await getMe({ token }));
    } catch {
      // Non-fatal: the redeem already succeeded; the badge lags until reload.
    }
  }, [getToken]);

  return (
    <>
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Gift className="size-6 text-primary" aria-hidden />
            Referrals
          </h1>
          <p className="text-sm text-muted-foreground">
            Invite friends to Menivor and earn credits when they join.
          </p>
        </div>
        <CreditsBadge credits={me?.credits} loading={status === "loading"} />
      </div>

      {status === "loading" && <ReferralSkeleton />}

      {status === "error" && (
        <ErrorPanel message={errorMessage} onRetry={() => void load()} />
      )}

      {status === "ready" && referral && (
        <div className="max-w-2xl space-y-6">
          <ReferralCard
            referral={referral}
            shareUrl={buildShareUrl(origin, referral.code)}
          />
          <RedeemForm onRedeemed={() => void refreshCredits()} />
        </div>
      )}
    </>
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
    <Badge
      variant="outline"
      className="gap-1.5 px-3 py-1"
      title="Available credits"
    >
      <Coins className="size-3.5 text-accent" aria-hidden />
      <span className="font-medium">{credits ?? 0}</span>
      <span className="text-muted-foreground">credits</span>
    </Badge>
  );
}

function ReferralSkeleton() {
  return (
    <div className="max-w-2xl space-y-6">
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
            <p className="font-medium">
              Couldn&apos;t load your referral details
            </p>
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
