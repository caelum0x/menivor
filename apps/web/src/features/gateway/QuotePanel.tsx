"use client";

import * as React from "react";
import { Calculator, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Quote } from "./api";
import { microsToUsd, usdToMicros } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface QuotePanelProps {
  keyId: string;
  /** Runs a live quote for this key against the gateway. */
  onQuote: (keyId: string, baseCostMicros: number) => Promise<Quote>;
}

/**
 * Inline price-quote widget for a single key: the reseller enters a base cost
 * (USD) and gets the marked-up customer price, today's spend, remaining
 * allowance, and whether the charge would be allowed — all from a live call.
 */
export function QuotePanel({ keyId, onQuote }: QuotePanelProps) {
  const [baseUsd, setBaseUsd] = React.useState("1.00");
  const [quote, setQuote] = React.useState<Quote | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const run = React.useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const result = await onQuote(keyId, usdToMicros(parseFloat(baseUsd || "0")));
      setQuote(result);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to quote."));
      setQuote(null);
    } finally {
      setBusy(false);
    }
  }, [keyId, baseUsd, onQuote]);

  return (
    <div className="space-y-2 border-t pt-3">
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-1">
          <Label htmlFor={`quote-${keyId}`} className="text-xs">
            Base cost (USD)
          </Label>
          <Input
            id={`quote-${keyId}`}
            inputMode="decimal"
            value={baseUsd}
            onChange={(e) => setBaseUsd(e.target.value)}
          />
        </div>
        <Button variant="outline" size="sm" onClick={() => void run()} disabled={busy}>
          {busy ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Calculator className="mr-1 h-4 w-4" aria-hidden />
          )}
          Quote
        </Button>
      </div>

      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}

      {quote && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs" data-testid="quote-result">
          <dt className="text-muted-foreground">Customer price</dt>
          <dd className="text-right font-medium">
            {microsToUsd(quote.customer_price_micros)}
          </dd>
          <dt className="text-muted-foreground">Spent today</dt>
          <dd className="text-right">{microsToUsd(quote.spent_today_micros)}</dd>
          <dt className="text-muted-foreground">Remaining</dt>
          <dd className="text-right">
            {quote.remaining_micros < 0
              ? "unlimited"
              : microsToUsd(quote.remaining_micros)}
          </dd>
          <dt className="text-muted-foreground">Would allow</dt>
          <dd
            className={
              quote.would_allow
                ? "text-right font-medium text-emerald-600"
                : "text-right font-medium text-destructive"
            }
          >
            {quote.would_allow ? "yes" : "no"}
          </dd>
        </dl>
      )}
    </div>
  );
}
