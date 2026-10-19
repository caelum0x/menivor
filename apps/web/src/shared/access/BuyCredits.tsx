"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApiToken } from "@/lib/use-api-token";
import { cn } from "@/lib/utils";
import { PaymentsPausedNotice, providerLabel, usePaymentsMode } from "@/src/shared/payments";
import { accessErrorMessage, startPackCheckout, type PackKey } from "./api";

interface Pack {
  readonly key: PackKey;
  readonly label: string;
}

/** Mirrors apps/api/app/services/billing/plans.py and the /pricing page. */
const PACKS: readonly Pack[] = [
  { key: "starter", label: "Buy 30 reels for $19" },
  { key: "pro", label: "120 reels for $59" },
];

/**
 * One click to a hosted checkout (the active payment provider) for a credit
 * pack. Credits land when the buyer returns, so there is nothing else to
 * click. While payments are paused it shows the calm "back soon" notice.
 */
export function BuyCredits({
  className,
  lead,
}: Readonly<{ className?: string; lead?: string }>) {
  const getToken = useApiToken();
  const [busy, setBusy] = React.useState<PackKey | null>(null);
  const [error, setError] = React.useState("");
  const { mode } = usePaymentsMode();

  const buy = async (key: PackKey) => {
    setError("");
    setBusy(key);
    try {
      const token = await getToken();
      const { checkout_url: url } = await startPackCheckout(key, { token });
      window.location.assign(url);
    } catch (err) {
      setError(accessErrorMessage(err));
      setBusy(null);
    }
  };

  if (mode.paused) {
    return <PaymentsPausedNotice mode={mode} className={className} newsletter={false} />;
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {lead ? <p className="text-sm text-muted-foreground">{lead}</p> : null}
      <div className="flex flex-wrap gap-2">
        {PACKS.map((pack, index) => (
          <Button
            key={pack.key}
            type="button"
            size="sm"
            variant={index === 0 ? "default" : "outline"}
            disabled={busy !== null}
            onClick={() => void buy(pack.key)}
          >
            {busy === pack.key ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            {pack.label}
          </Button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        1 credit renders 1 reel. Credits never expire. Paid securely through {providerLabel(mode.provider)}.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
