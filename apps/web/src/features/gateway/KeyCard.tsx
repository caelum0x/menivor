"use client";

import * as React from "react";
import { Ban, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ProvisioningKey, Quote } from "./api";
import { bpsToPercent, microsToUsd } from "./api";
import { QuotePanel } from "./QuotePanel";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface KeyCardProps {
  keyRow: ProvisioningKey;
  /** Revokes (disables) this key against the gateway. */
  onRevoke: (keyId: string) => Promise<void>;
  /** Runs a live price quote for this key. */
  onQuote: (keyId: string, baseCostMicros: number) => Promise<Quote>;
}

/**
 * A single provisioning-key card: markup + cap summary, a revoke action for
 * active keys, and an inline quote panel. All actions hit the live gateway.
 */
export function KeyCard({ keyRow, onRevoke, onQuote }: KeyCardProps) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const revoke = React.useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      await onRevoke(keyRow.id);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to revoke."));
    } finally {
      setBusy(false);
    }
  }, [keyRow.id, onRevoke]);

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-center justify-between gap-2">
          <p className="font-medium">{keyRow.label || "Untitled key"}</p>
          {keyRow.disabled ? (
            <Badge variant="outline">revoked</Badge>
          ) : (
            <Badge>active</Badge>
          )}
        </div>

        <p className="text-sm text-muted-foreground">
          {bpsToPercent(keyRow.markup_bps)} markup ·{" "}
          {keyRow.daily_cap_micros > 0
            ? `${microsToUsd(keyRow.daily_cap_micros)}/day cap`
            : "unlimited"}
          {keyRow.min_fee_micros > 0
            ? ` · ${microsToUsd(keyRow.min_fee_micros)} min fee`
            : ""}
        </p>

        {!keyRow.disabled && (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => void revoke()}
            disabled={busy}
          >
            {busy ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Ban className="mr-1 h-4 w-4" aria-hidden />
            )}
            Revoke
          </Button>
        )}

        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}

        {!keyRow.disabled && <QuotePanel keyId={keyRow.id} onQuote={onQuote} />}
      </CardContent>
    </Card>
  );
}
