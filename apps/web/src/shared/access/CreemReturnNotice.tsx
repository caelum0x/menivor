"use client";

import Link from "next/link";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCreemReturn } from "./use-creem-return";

/**
 * Shown on the page the payment provider returns buyers to: confirms the
 * payment automatically and says how many credits landed, with the next action.
 */
export function CreemReturnNotice() {
  const payment = useCreemReturn();
  if (payment.phase === "none") return null;
  if (payment.phase === "confirming") {
    return (
      <p role="status" className="flex items-center gap-2 rounded-md border border-border p-4 text-sm">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Confirming your payment…
      </p>
    );
  }
  if (payment.phase === "pending") {
    return (
      <p role="status" className="flex items-center gap-2 rounded-md border border-border p-4 text-sm">
        <Loader2 className="size-4 animate-spin" aria-hidden /> {payment.message}
      </p>
    );
  }
  if (payment.phase === "failed") {
    return (
      <p role="alert" className="flex items-start gap-2 rounded-md border border-destructive/40 p-4 text-sm text-destructive">
        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden /> {payment.message}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3 rounded-md border border-primary/40 bg-primary/5 p-4 sm:flex-row sm:items-center sm:justify-between">
      <p className="flex items-center gap-2 text-sm">
        <CheckCircle2 className="size-4 text-primary" aria-hidden />
        {payment.result.subscription
          ? `Plan active. ${payment.result.credits} reels added, ${payment.result.balance} available.`
          : `Payment confirmed. ${payment.result.credits} credits added, ${payment.result.balance} available.`}
      </p>
      <Button asChild size="sm">
        <Link href="/create">Make reels now</Link>
      </Button>
    </div>
  );
}

/** Neutral alias used by new code. */
export const PaymentReturnNotice = CreemReturnNotice;
