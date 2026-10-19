"use client";

import * as React from "react";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CreateKeyBody, ProvisioningKey } from "./api";
import { usdToMicros } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface MintKeyFormProps {
  /** Mints the key against the gateway and returns the created row (with secret). */
  onMint: (body: CreateKeyBody) => Promise<ProvisioningKey>;
}

/**
 * Mint-a-provisioning-key form. Collects a label, daily USD cap, markup %, and a
 * per-call minimum fee, converts them to the wallet's integer-micro/basis-point
 * units, and surfaces the write-once secret on success.
 */
export function MintKeyForm({ onMint }: MintKeyFormProps) {
  const [label, setLabel] = React.useState("");
  const [capUsd, setCapUsd] = React.useState("100");
  const [markupPct, setMarkupPct] = React.useState("20");
  const [minFeeUsd, setMinFeeUsd] = React.useState("0");
  const [secret, setSecret] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const submit = React.useCallback(async () => {
    setBusy(true);
    setError("");
    setSecret("");
    try {
      const key = await onMint({
        label: label.trim(),
        daily_cap_micros: usdToMicros(parseFloat(capUsd || "0")),
        markup_bps: Math.round(parseFloat(markupPct || "0") * 100),
        min_fee_micros: usdToMicros(parseFloat(minFeeUsd || "0")),
      });
      if (key.secret) setSecret(key.secret);
      setLabel("");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to mint key."));
    } finally {
      setBusy(false);
    }
  }, [label, capUsd, markupPct, minFeeUsd, onMint]);

  return (
    <Card>
      <CardContent className="space-y-4 py-5">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" aria-hidden />
          <h2 className="font-semibold">Mint provisioning key</h2>
        </div>

        <div className="space-y-1">
          <Label htmlFor="gw-label">Label</Label>
          <Input
            id="gw-label"
            placeholder="e.g. Acme reseller"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="gw-cap">Daily cap (USD, 0 = unlimited)</Label>
            <Input
              id="gw-cap"
              inputMode="decimal"
              value={capUsd}
              onChange={(e) => setCapUsd(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="gw-markup">Markup (%)</Label>
            <Input
              id="gw-markup"
              inputMode="decimal"
              value={markupPct}
              onChange={(e) => setMarkupPct(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="gw-minfee">Min fee (USD)</Label>
            <Input
              id="gw-minfee"
              inputMode="decimal"
              value={minFeeUsd}
              onChange={(e) => setMinFeeUsd(e.target.value)}
            />
          </div>
        </div>

        <Button onClick={() => void submit()} disabled={busy}>
          {busy ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
          ) : null}
          Mint key
        </Button>

        {secret && (
          <div className="rounded-md border border-primary/40 bg-primary/5 p-3 text-sm">
            <p className="mb-1 flex items-center gap-1 font-medium text-primary">
              <ShieldCheck className="h-4 w-4" aria-hidden /> Copy your secret now —
              shown once
            </p>
            <code className="break-all text-xs" data-testid="gw-secret">
              {secret}
            </code>
          </div>
        )}
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
