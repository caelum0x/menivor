"use client";

import { NewsletterForm } from "@/components/marketing/NewsletterForm";
import { cn } from "@/lib/utils";
import type { PaymentsMode } from "@/lib/types";
import { pausedCopy } from "./mode";

/**
 * Calm "paid plans are back soon" state shown instead of buy buttons while
 * payments are paused, with the newsletter signup so buyers hear when they return.
 */
export function PaymentsPausedNotice({
  mode,
  className,
  newsletter = true,
}: Readonly<{ mode: PaymentsMode; className?: string; newsletter?: boolean }>) {
  return (
    <div
      role="status"
      data-testid="payments-paused"
      className={cn("space-y-4 rounded-lg border border-border bg-muted/30 p-5", className)}
    >
      <p className="text-sm text-foreground">{pausedCopy(mode)}</p>
      {newsletter ? (
        <NewsletterForm
          title="Get a note when paid plans are back"
          blurb="One email when checkout reopens, plus the occasional product update."
          submitLabel="Notify me"
        />
      ) : null}
    </div>
  );
}
