"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import { PaymentsPausedNotice, usePaymentsMode } from "@/src/shared/payments";
import {
  getPremiumStatus,
  planErrorMessage,
  startPremiumCheckout,
  type PremiumKind,
  type PremiumPack,
  type PremiumStatus,
} from "./api";

/** Web-owned copy per balance (never the provider or model name). */
export const PREMIUM_COPY: Readonly<Record<PremiumKind, { title: string; unit: string; body: string }>> = {
  premium_voice: {
    title: "Premium voice",
    unit: "premium voice reels",
    body: "Studio voices and music for your reels. Without it, reels use the free voice for their language.",
  },
  ai_video: {
    title: "AI video clips",
    unit: "AI video credits",
    body: "Generated video clips, charged at three times what the clip costs us. A failed clip gives its credits back.",
  },
};

function formatPackPrice(usd: number): string {
  return Number.isInteger(usd) ? `$${usd}` : `$${usd.toFixed(2)}`;
}

function PackRow({ pack, balance }: Readonly<{ pack: PremiumPack; balance: number }>) {
  const getToken = useApiToken();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const copy = PREMIUM_COPY[pack.kind];

  const buy = async () => {
    setError("");
    setBusy(true);
    try {
      const token = await getToken();
      const { checkout_url: url } = await startPremiumCheckout(pack.key, { token });
      window.location.assign(url);
    } catch (err) {
      setError(planErrorMessage(err));
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border p-5">
      <div className="space-y-1">
        <p className="text-sm font-medium">{copy.title}</p>
        <p className="text-2xl font-semibold tracking-tight">{formatPackPrice(pack.price_usd)}</p>
        <p className="text-sm text-muted-foreground">
          {pack.credits} {copy.unit}, one-time. You have {balance}.
        </p>
        <p className="text-sm text-muted-foreground">{copy.body}</p>
      </div>
      <Button
        type="button"
        variant="outline"
        className="mt-auto"
        disabled={busy || !pack.available}
        onClick={() => void buy()}
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
        {pack.available ? `Buy ${copy.title.toLowerCase()}` : "Not on sale yet"}
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </li>
  );
}

/** Premium balances plus the one-time packs, over an already-loaded status. */
export function PremiumPacksView({
  status,
  className,
}: Readonly<{ status: PremiumStatus; className?: string }>) {
  const { mode } = usePaymentsMode();
  if (!status.packs.length) return null;
  return (
    <section className={cn("space-y-4", className)} aria-labelledby="premium-packs-title">
      <div className="space-y-1">
        <h2 id="premium-packs-title" className="text-xl font-semibold tracking-tight">
          Premium add-ons
        </h2>
        <p className="text-sm text-muted-foreground">
          Reel credits and plans never pay for these; each has its own balance.
        </p>
      </div>
      {mode.paused ? (
        <PaymentsPausedNotice mode={mode} />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {status.packs.map((pack) => (
            <PackRow key={pack.key} pack={pack} balance={status.balances[pack.kind]} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** Signed-in block: loads the caller's premium balances and packs. */
export function PremiumPacks({ className }: Readonly<{ className?: string }>) {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getToken = useApiToken();
  const [status, setStatus] = React.useState<PremiumStatus | null>(null);

  React.useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    let active = true;
    void (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        const next = await getPremiumStatus({ token });
        if (active) setStatus(next);
      } catch {
        // Older API or a transient failure: the block stays hidden.
      }
    })();
    return () => {
      active = false;
    };
  }, [isLoaded, isSignedIn, getToken]);

  return status ? <PremiumPacksView status={status} className={className} /> : null;
}
